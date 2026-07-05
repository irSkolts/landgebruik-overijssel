// Build data/parcels.pmtiles from data/parcels.geojson.
//
// Pipeline: geojson-vt slices the parcels into a vector-tile pyramid,
// vt-pbf encodes each tile to MVT, tiles are gzipped, and everything is
// written into a single PMTiles v3 archive (root-directory-only, which is
// fine for this small tileset). The result is validated by reading a few
// tiles back with the pmtiles reader.
//
// Usage:  node --max-old-space-size=4096 make_tiles.mjs
// (or: npm run tiles)

import { readFileSync, writeFileSync } from "fs";
import { gzipSync } from "zlib";
import { createHash } from "crypto";
import geojsonvt from "geojson-vt";
import vtpbf from "vt-pbf";
import { PMTiles, zxyToTileId } from "pmtiles";

const SRC = "data/parcels.geojson";
const OUT = "data/parcels.pmtiles";
const LAYER = "parcels";
const MINZOOM = 8;
const MAXZOOM = 14;
const EXTENT = 4096;

const log = (m) => console.log(m);

// ---- tile <-> lon/lat helpers ----------------------------------------
const lon2x = (lon, z) => Math.floor(((lon + 180) / 360) * 2 ** z);
const lat2y = (lat, z) => {
  const r = (lat * Math.PI) / 180;
  return Math.floor(
    ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z
  );
};

// ---- unsigned LEB128 varint ------------------------------------------
function writeVarint(arr, n) {
  while (n >= 0x80) {
    arr.push((n & 0x7f) | 0x80);
    n = Math.floor(n / 128);
  }
  arr.push(n);
}

// PMTiles v3 directory: counts, then delta tile-ids, run-lengths,
// lengths, and offsets (0 = contiguous with previous entry).
function serializeDirectory(entries) {
  const a = [];
  writeVarint(a, entries.length);
  let last = 0;
  for (const e of entries) {
    writeVarint(a, e.tileId - last);
    last = e.tileId;
  }
  for (const e of entries) writeVarint(a, e.runLength);
  for (const e of entries) writeVarint(a, e.length);
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    if (i > 0 && e.offset === entries[i - 1].offset + entries[i - 1].length) {
      writeVarint(a, 0);
    } else {
      writeVarint(a, e.offset + 1);
    }
  }
  return Buffer.from(a);
}

// ---- read + index -----------------------------------------------------
log(`Reading ${SRC} ...`);
const gj = JSON.parse(readFileSync(SRC, "utf8"));
log(`  ${gj.features.length} features`);

let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90;
const scan = (c) => {
  if (typeof c[0] === "number") {
    if (c[0] < minLon) minLon = c[0];
    if (c[0] > maxLon) maxLon = c[0];
    if (c[1] < minLat) minLat = c[1];
    if (c[1] > maxLat) maxLat = c[1];
  } else for (const x of c) scan(x);
};
for (const f of gj.features) scan(f.geometry.coordinates);
log(`  bbox ${minLon.toFixed(3)},${minLat.toFixed(3)} .. ${maxLon.toFixed(3)},${maxLat.toFixed(3)}`);

log("Indexing with geojson-vt ...");
const index = geojsonvt(gj, {
  maxZoom: MAXZOOM,
  indexMaxZoom: 6,
  tolerance: 3,
  extent: EXTENT,
  buffer: 64,
});

// ---- encode every non-empty tile in the bbox, per zoom ----------------
const tiles = []; // { tileId, data(gzip) }
const perZoom = {};
for (let z = MINZOOM; z <= MAXZOOM; z++) {
  const x0 = lon2x(minLon, z), x1 = lon2x(maxLon, z);
  const y0 = lat2y(maxLat, z), y1 = lat2y(minLat, z); // note: y grows south
  let n = 0, bytes = 0;
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      const t = index.getTile(z, x, y);
      if (!t || !t.features || t.features.length === 0) continue;
      const pbf = vtpbf.fromGeojsonVt({ [LAYER]: t }, { version: 2, extent: EXTENT });
      const gz = gzipSync(Buffer.from(pbf), { level: 9 });
      tiles.push({ tileId: zxyToTileId(z, x, y), z, x, y, data: gz });
      n++; bytes += gz.length;
    }
  }
  perZoom[z] = { n, bytes };
  log(`  z${z}: ${n} tiles, ${(bytes / 1e6).toFixed(2)} MB`);
}

// ---- assemble PMTiles (clustered, root-only directory) ----------------
tiles.sort((a, b) => a.tileId - b.tileId);

const byHash = new Map();
const dataParts = [];
let offset = 0;
const entries = [];
for (const t of tiles) {
  const h = createHash("md5").update(t.data).digest("hex");
  let u = byHash.get(h);
  if (!u) {
    u = { offset, length: t.data.length };
    byHash.set(h, u);
    dataParts.push(t.data);
    offset += t.data.length;
  }
  entries.push({ tileId: t.tileId, offset: u.offset, length: u.length, runLength: 1 });
}
const tileData = Buffer.concat(dataParts);

const rootDir = gzipSync(serializeDirectory(entries));
const metadata = gzipSync(Buffer.from(JSON.stringify({
  name: "Overijssel BRP gewaspercelen",
  format: "pbf",
  minzoom: MINZOOM,
  maxzoom: MAXZOOM,
  bounds: [minLon, minLat, maxLon, maxLat],
  vector_layers: [{
    id: LAYER, minzoom: MINZOOM, maxzoom: MAXZOOM,
    fields: { g: "Number", c: "String", h: "Number", z: "Number" },
  }],
})));

const HEADER = 127;
const rootOffset = HEADER;
const metaOffset = rootOffset + rootDir.length;
const leafOffset = metaOffset + metadata.length;
const tileDataOffset = leafOffset; // no leaf directories

const header = Buffer.alloc(HEADER);
header.write("PMTiles", 0, "ascii");
header.writeUInt8(3, 7);
header.writeBigUInt64LE(BigInt(rootOffset), 8);
header.writeBigUInt64LE(BigInt(rootDir.length), 16);
header.writeBigUInt64LE(BigInt(metaOffset), 24);
header.writeBigUInt64LE(BigInt(metadata.length), 32);
header.writeBigUInt64LE(BigInt(leafOffset), 40);
header.writeBigUInt64LE(BigInt(0), 48);
header.writeBigUInt64LE(BigInt(tileDataOffset), 56);
header.writeBigUInt64LE(BigInt(tileData.length), 64);
header.writeBigUInt64LE(BigInt(entries.length), 72); // addressed tiles
header.writeBigUInt64LE(BigInt(entries.length), 80); // tile entries
header.writeBigUInt64LE(BigInt(byHash.size), 88);    // tile contents
header.writeUInt8(1, 96);  // clustered
header.writeUInt8(2, 97);  // internal compression: gzip
header.writeUInt8(2, 98);  // tile compression: gzip
header.writeUInt8(1, 99);  // tile type: MVT
header.writeUInt8(MINZOOM, 100);
header.writeUInt8(MAXZOOM, 101);
header.writeInt32LE(Math.round(minLon * 1e7), 102);
header.writeInt32LE(Math.round(minLat * 1e7), 106);
header.writeInt32LE(Math.round(maxLon * 1e7), 110);
header.writeInt32LE(Math.round(maxLat * 1e7), 114);
header.writeUInt8(MINZOOM, 118);
header.writeInt32LE(Math.round(((minLon + maxLon) / 2) * 1e7), 119);
header.writeInt32LE(Math.round(((minLat + maxLat) / 2) * 1e7), 123);

writeFileSync(OUT, Buffer.concat([header, rootDir, metadata, tileData]));
const total = HEADER + rootDir.length + metadata.length + tileData.length;
log(`\nWrote ${OUT}`);
log(`  ${entries.length} tile entries, ${byHash.size} unique tiles`);
log(`  root dir ${(rootDir.length / 1024).toFixed(1)} KB (first fetch = header+rootdir = ${((HEADER + rootDir.length) / 1024).toFixed(1)} KB)`);
log(`  total ${(total / 1e6).toFixed(1)} MB`);

// ---- validate by reading tiles back ----------------------------------
const buf = readFileSync(OUT);
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const source = {
  getKey: () => OUT,
  async getBytes(o, l) {
    return { data: ab.slice(o, o + l) };
  },
};
const p = new PMTiles(source);
const h = await p.getHeader();
if (h.maxZoom !== MAXZOOM || h.tileType !== 1) throw new Error("header mismatch");
let checked = 0;
for (const t of [tiles[0], tiles[(tiles.length / 2) | 0], tiles[tiles.length - 1]]) {
  const res = await p.getZxy(t.z, t.x, t.y);
  if (!res) throw new Error(`tile ${t.z}/${t.x}/${t.y} not found on read-back`);
  // reader already gunzips the tile; res.data is decoded MVT bytes
  if (!res.data || res.data.byteLength === 0)
    throw new Error(`tile ${t.z}/${t.x}/${t.y} empty on read-back`);
  checked++;
}
log(`  validation OK: header + ${checked} sample tiles read back`);
