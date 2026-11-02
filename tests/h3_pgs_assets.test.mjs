import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const pgs = new URL("../../ComfyUI-MiniMaxH3-Ref-PGS/web/", import.meta.url);
const dataUrl = text => `data:text/javascript;base64,${Buffer.from(text).toString("base64")}`;
const utils = (await readFile(new URL("pgs_utils.mjs", pgs), "utf8"))
  .replace('import { api } from "/scripts/api.js";', 'const api = { apiURL: path => path };');
const source = (await readFile(new URL("pgs_collect.mjs", pgs), "utf8"))
  .replace('"./pgs_utils.mjs"', JSON.stringify(dataUrl(utils)));
const { collectPgsAssets } = await import(dataUrl(source));

function graph() {
  const g = { _nodes: [], links: {}, getNodeById(id) { return this._nodes.find(n => n.id === id); } };
  const add = (id, type, widgets = {}) => {
    const node = { id, type, graph: g, inputs: [], widgets: Object.entries(widgets).map(([name,value]) => ({ name,value })) };
    g._nodes.push(node); return node;
  };
  let linkId = 0;
  const connect = (source, target, name) => {
    const link = ++linkId; target.inputs.push({ name, link }); g.links[link] = { origin_id: source.id };
  };
  return { g, add, connect };
}

test("dynamic references appear in @ order, skipping unconnected slots and unrelated markers", () => {
  const { g, add, connect } = graph();
  const image1 = add(1, "LoadImage", { image: "hero.png" });
  const image2 = add(2, "LoadImage", { image: "scene.png" });
  const collection = add(3, "YtonH3ReferenceAssets");
  const editor = add(4, "MiniMaxH3RefPGSScenePromptEditor");
  add(5, "MiniMaxH3RefPGSPictureAsset", { alias: "Unused" });
  connect(image2, collection, "images.参考图 9");
  connect(image1, collection, "images.参考图 1");
  collection.inputs.push({ name: "images.参考图 2", link: null });
  connect(collection, editor, "assets");
  let assets = collectPgsAssets(g, editor);
  assert.deepEqual(assets.map(a => [a.alias, a.nativeLabel]), [["Picture_1", "<Picture 1>"], ["Picture_2", "<Picture 2>"]]);
  assert.equal(assets[0].source, image1);
  assert.match(assets[0].previewUrl, /hero.png/);
  collection.inputs.find(i => i.name === "images.参考图 1").link = null;
  assets = collectPgsAssets(g, editor);
  assert.equal(assets.length, 1);
  assert.equal(assets[0].source, image2);
  assert.equal(assets[0].nativeLabel, "<Picture 1>");
});

test("PGS names and direct references share one numbering with source video and audio", () => {
  const { g, add, connect } = graph();
  const image1 = add(1, "LoadImage", { image: "hero.png" });
  const image2 = add(2, "LoadImage", { image: "scene.png" });
  const hero = add(3, "MiniMaxH3RefPGSPictureAsset", { alias: "Hero", label: "人物" });
  const scene = add(4, "MiniMaxH3RefPGSPictureAsset", { alias: "Scene", label: "场景", scenes: "1:3" });
  const collection = add(5, "YtonH3ReferenceAssets");
  const editor = add(6, "MiniMaxH3RefPGSScenePromptEditor");
  const video = add(7, "LoadVideo", { video: "action.mp4" });
  connect(image1, hero, "image"); connect(image2, scene, "image"); connect(hero, scene, "previous");
  connect(scene, collection, "pgs_images"); connect(image2, collection, "images.参考图 1");
  connect(video, collection, "video_frames"); connect(video, collection, "video_audio");
  connect(collection, editor, "assets");
  const assets = collectPgsAssets(g, editor);
  assert.deepEqual(assets.map(a => [a.alias,a.nativeLabel]), [
    ["Hero", "<Picture 1>"], ["Scene", "<Picture 2>"], ["Picture_3", "<Picture 3>"],
    ["Video_1", "<Video 1>"], ["Video_1_audio", "<Audio 1>"]]);
  assert.equal(assets[1].scenes, "1:3");
  hero.widgets.find(w => w.name === "alias").value = "Person";
  assert.equal(collectPgsAssets(g, editor)[0].alias, "Person");
});

test("native PGS chain still supplies @ names without a collection", () => {
  const { g, add, connect } = graph();
  const hero = add(1, "MiniMaxH3RefPGSPictureAsset", { alias: "Hero" });
  const editor = add(2, "MiniMaxH3RefPGSScenePromptEditor");
  add(3, "MiniMaxH3RefPGSPictureAsset", { alias: "Unrelated" });
  connect(hero, editor, "assets");
  assert.deepEqual(collectPgsAssets(g, editor).map(a => a.alias), ["Hero"]);
});
