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
  widgets: Object.entries({ ...values, enable_context: false, sampling_mode: '二采',
    film_model: 'h3_clean_latent_upscaler_film_epoch200.safetensors', film_method: 'learned model',
    film_audio_denoise: 0, film_noise_resample: 'independent', film_match_stats: 0, face_sigmas: '',
    second_sigma_values: '', second_steps: 4, second_sigma_start: 0.4, second_rho: 7, film_ff_chunks: '8' })
    .filter(([name]) => !['latent_path', 'context_path', 'first_pass_scale', 'upscale_model',
      'face_steps', 'face_denoise', 'face_large_strength', 'face_detector', 'face_fallback_detector', 'face_seed'].includes(name))
    .map(([name, value]) => ({ name, value })),
  inputs: ['sigmas', 'second_sigma_values', 'face_sigmas', 'image', 'video', 'audio', 'previous_video'].map(name => ({ name, link: null })),
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
const videoWidgets = new Map(videoNode.widgets.map(w => [w.name, w]))
function videoChange(name, value) { const w = videoWidgets.get(name); w.value = value; w.callback() }
assert.equal(videoNode.widgets.filter(w => w.name.startsWith('face_')).map(w => w.name).join(','),
  'face_refine,face_count,face_sigmas,face_reverse')
videoChange('face_refine', true)
assert.equal(videoWidgets.get('face_count').disabled, false)
assert.equal(videoWidgets.get('face_sigmas').disabled, false)
assert.equal(videoWidgets.get('face_reverse').disabled, false)
videoChange('face_refine', false)
assert.equal(videoWidgets.get('first_pass_scale').value, 0.5)
assert.ok(videoWidgets.get('first_pass_scale').disabled)
assert.equal(videoWidgets.get('first_pass_scale').serialize, false)
assert.equal(videoWidgets.get('sampling_plan').value, 'Film 2×')
assert.ok(videoWidgets.get('sampling_plan').disabled)
assert.equal(videoWidgets.get('sampling_plan').serialize, false)
assert.ok(!videoWidgets.has('upscale_model'))
assert.ok(!videoWidgets.has('selflift_transition_step'))
assert.equal(videoWidgets.get('film_model').disabled, false)
for (const name of ['film_method', 'film_model', 'film_ff_chunks', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
  assert.ok(videoNode.widgets.indexOf(videoWidgets.get(name)) > videoNode.widgets.findIndex(w => w.name === 'h3_section_二采方案'))
  assert.ok(videoNode.widgets.indexOf(videoWidgets.get(name)) < videoNode.widgets.findIndex(w => w.name === 'h3_section_小脸修复'))
  assert.equal(videoWidgets.get(name).disabled, false)
}
assert.match(videoWidgets.get('film_match_stats').label, /当前方式忽略/)
videoChange('film_method', 'bicubic')
assert.equal(videoWidgets.get('film_match_stats').label, '统计匹配 / match_stats')
videoChange('film_method', 'learned model')
videoNode.inputs.push({ name: 'film_method', link: 23 })
videoNode.onConnectionsChange()
assert.equal(videoWidgets.get('film_match_stats').label, '统计匹配 / match_stats')
videoNode.inputs.find(i => i.name === 'film_method').link = null
videoNode.onConnectionsChange()
assert.match(videoWidgets.get('film_match_stats').label, /当前方式忽略/)
assert.equal(videoWidgets.get('second_sampler').disabled, false)
assert.equal(videoWidgets.get('second_sigma_values').disabled, false)
const autoSecond = ['second_steps', 'second_sigma_start', 'second_rho']
for (const name of autoSecond) assert.equal(videoWidgets.get(name).disabled, false)
videoChange('second_sigma_values', '0.4, 0.2, 0')
for (const name of autoSecond) assert.ok(videoWidgets.get(name).disabled)
videoChange('second_sigma_values', '  ')
for (const name of autoSecond) assert.equal(videoWidgets.get(name).disabled, false)
videoChange('first_pass_scale', 0.8)
assert.equal(videoWidgets.get('first_pass_scale').value, 0.5)
videoNode.inputs.find(i => i.name === 'second_sigma_values').link = 22
videoNode.onConnectionsChange()
assert.ok(videoWidgets.get('second_sigma_values').disabled)
for (const name of autoSecond) assert.ok(videoWidgets.get(name).disabled)
videoChange('sampling_mode', '单采')
const hiddenSecond = ['h3_section_二采方案', 'sampling_plan', 'first_pass_scale', 'film_method', 'film_model',
  'film_ff_chunks', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats', 'second_sampler',
  'second_sigma_values', ...autoSecond]
for (const name of hiddenSecond) {
  assert.ok(videoWidgets.get(name).hidden)
  assert.equal(videoWidgets.get(name).type, 'hidden')
}
assert.equal(videoWidgets.get('h3_context_length').hidden, undefined)
for (const name of ['film_method', 'film_model', 'film_ff_chunks', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
  assert.ok(videoWidgets.get(name).disabled)
}
assert.ok(videoWidgets.get('film_model').disabled)
assert.ok(videoWidgets.get('first_pass_scale').disabled)
assert.ok(videoWidgets.get('second_sampler').disabled)
videoChange('sampling_mode', '二采')
for (const name of hiddenSecond) assert.equal(videoWidgets.get(name).hidden, false)
assert.equal(videoWidgets.get('h3_section_二采方案').type, 'h3_section')
assert.equal(videoWidgets.get('first_pass_scale').type, 'h3_context_info')
for (const name of ['film_method', 'film_model', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
  assert.equal(videoWidgets.get(name).disabled, false)
}
assert.equal(videoWidgets.get('first_pass_scale').value, 0.5)
assert.ok(videoWidgets.get('first_pass_scale').disabled)
assert.equal(videoWidgets.get('film_model').disabled, false)
assert.equal(videoWidgets.get('second_sampler').disabled, false)
assert.ok(videoWidgets.get('second_sigma_values').disabled)
videoNode.inputs.find(i => i.name === 'second_sigma_values').link = null
videoNode.onConnectionsChange()
for (const name of autoSecond) assert.equal(videoWidgets.get(name).disabled, false)
assert.equal(videoWidgets.get('width').label, '最终宽度')
console.log('H3 controls: Film 2×, fixed visible ratio, Sigma links, single pass and face controls passed.')
