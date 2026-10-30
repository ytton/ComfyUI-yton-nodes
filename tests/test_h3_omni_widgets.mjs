import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

let extension
const app = { registerExtension(value) { extension = value } }
const source = fs.readFileSync(new URL('../web/h3_omni_widgets.js', import.meta.url), 'utf8').replace(/^import .*\n/, '')
vm.runInNewContext(source, { app, LiteGraph: { NODE_TEXT_COLOR: '#fff' } })
const values = {
  prompt: '', width: 1344, height: 768, mode: '普通模式', duration: 5, ref_image_size: 'match',
  sampling_mode: '单采', steps: 4, sampler_name: 'euler', scheduler: 'simple', denoise: 1,
  first_pass_scale: 0.625, upscale_model: 'model.safetensors', second_sampler: 'sa_solver',
  second_sigma_values: '0.6,0.3,0', face_refine: false, face_count: 1, face_steps: 4,
  face_denoise: 0.4, face_detector: 'face.pt', face_reverse: false,
  face_large_strength: 0.35, face_fallback_detector: 'none', face_seed: 42,
  seed: 1, control_after_generate: 'fixed', latent_path: 'context', clip_index: 1, context_path: '',
}
const node = {
  comfyClass: 'YtonH3OmniGenerate', widgets: Object.entries(values).map(([name, value]) => ({ name, value })),
  inputs: ['sigmas', 'second_sigmas', 'face_sigmas'].map(name => ({ name, link: null })), outputs: [], size: [400, 500],
  addCustomWidget(widget) { this.widgets.push(widget); return widget },
  computeSize() { return [460, 1000] }, setDirtyCanvas() {}, setSize(size) { this.size = size },
}
extension.nodeCreated(node)
const widgets = new Map(node.widgets.map(widget => [widget.name, widget]))
function change(name, value) { const widget = widgets.get(name); widget.value = value; widget.callback() }
assert.ok(widgets.get('first_pass_scale').disabled)
assert.ok(widgets.get('face_steps').disabled)
change('sampling_mode', '二采')
assert.equal(widgets.get('first_pass_scale').disabled, false)
change('face_refine', true)
assert.equal(widgets.get('face_steps').disabled, false)
node.inputs[2].link = 3
node.onConnectionsChange()
assert.ok(widgets.get('face_steps').disabled)
assert.ok(widgets.get('face_denoise').disabled)
assert.equal(widgets.get('first_pass_scale').disabled, false)
assert.equal(widgets.get('face_large_strength').disabled, false)
change('mode', '复刻模式')
assert.ok(widgets.get('duration').disabled)
node.inputs[0].link = 1
node.inputs[1].link = 2
node.onConnectionsChange()
assert.ok(widgets.get('steps').disabled)
assert.ok(widgets.get('second_sigma_values').disabled)
assert.equal(widgets.get('face_steps').disabled, true)
assert.equal(node.widgets.filter(w => w.name === 'h3_context_length').length, 1)
assert.equal(widgets.get('h3_context_length').serialize, false)
for (const name of Object.keys(values)) assert.ok(widgets.has(name), `missing ${name}`)
const videoNode = {
  ...node,
  comfyClass: 'YtonH3VideoContextOmniGenerate',
  widgets: Object.entries({ ...values, enable_context: false }).filter(([name]) => !['latent_path', 'context_path'].includes(name)).map(([name, value]) => ({ name, value })),
  inputs: ['sigmas', 'second_sigmas', 'face_sigmas', 'image', 'video', 'audio', 'previous_video'].map(name => ({ name, link: null })),
  outputs: [{ name: 'video' }, { name: 'av_latent' }],
  onConfigure: undefined, onConnectionsChange: undefined,
}
extension.nodeCreated(videoNode)
assert.equal(videoNode.inputs.find(input => input.name === 'previous_video').label, '上一段视频（可选）')
for (const [name, label] of [['image', '图片'], ['video', '视频'], ['audio', '音频']]) {
  assert.equal(videoNode.inputs.find(input => input.name === name).label, label)
}
assert.equal(videoNode.outputs[0].label, '本段视频')
assert.ok(!videoNode.widgets.some(widget => ['latent_path', 'context_path'].includes(widget.name)))
assert.ok(videoNode.widgets.some(widget => widget.name === 'clip_index'))
const contextToggle = videoNode.widgets.find(widget => widget.name === 'enable_context')
assert.equal(contextToggle.label, '启用上下文')
assert.equal(contextToggle.value, false)
assert.equal(videoNode.widgets.indexOf(contextToggle) + 1, videoNode.widgets.findIndex(widget => widget.name === 'clip_index'))
videoNode.inputs.find(input => input.name === 'previous_video').link = 9
videoNode.onConnectionsChange()
assert.equal(contextToggle.value, false)
contextToggle.value = true
videoNode.onConfigure()
assert.equal(contextToggle.value, true)
assert.ok(!widgets.has('enable_context'))
console.log('H3 node controls: single/two-pass, face toggle, replica duration and independent sigma sockets passed.')
