import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

let extension
const app = { registerExtension(value) { extension = value } }
const source = fs.readFileSync(new URL('../web/h3_omni_widgets.js', import.meta.url), 'utf8').replace(/^import[^\n]*\n/, '')
vm.runInNewContext(source, { app, LiteGraph: { NODE_TEXT_COLOR: '#fff', GRID_SHAPE: 6 } })
const common = {
  prompt: '', width: 1344, height: 768, mode: '普通模式', duration: 5, ref_image_size: 'match',
  sampling_mode: '二采', steps: 4, sampler_name: 'euler', scheduler: 'simple', denoise: 1,
  seed: 1, control_after_generate: 'fixed', enable_context: false, context_auto_extend: true,
  debug_keep_context: false,
  enable_add_guide: false, guide_frame_idx: 0,
  context_noise_strength: 0.1, context_color_strength: 0.75,
  face_refine: false, face_count: 1, face_sigmas: '', face_reverse: false, second_ff_chunks: '8',
}
const second = { second_sampler: 'euler', second_sigma_values: '', second_steps: 4, second_sigma_start: 0.4, second_rho: 7 }
const plans = {
  YtonH3VideoContextOmniGenerate: { ...second, film_model: 'film.safetensors', film_method: 'learned model',
    film_audio_denoise: 0, film_noise_resample: 'independent', film_match_stats: 0 },
  YtonH3SelfLiftOmniGenerate: { first_pass_scale: 0.5, upscale_model: 'lms.safetensors',
    selflift_transition_step: 2, selflift_rho: 0, selflift_w_min: 0.5, selflift_w_max: 1,
    selflift_highres_tiling: false, selflift_highres_tiles: 'auto' },
  YtonH3TraditionalOmniGenerate: { ...second, first_pass_scale: 0.625, upscale_model: 'lms.safetensors' },
}
for (const [comfyClass, specific] of Object.entries(plans)) {
  const node = {
    comfyClass, widgets: Object.entries({ ...common, ...specific }).map(([name, value]) => ({ name, value })),
    inputs: ['model', 'clip', 'vae', 'audio_vae', 'image', 'video', 'audio', 'sigmas', 'second_model', 'face_model', 'previous_video', 'guide_video', 'guide_image', 'guide_audio',
      'face_sigmas', ...('second_sigma_values' in specific ? ['second_sigma_values'] : [])].map(name => ({ name, link: null })),
    outputs: [{ name: 'video' }, { name: 'av_latent' }], size: [400, 500],
    constructor: { nodeData: { input: {
      required: Object.fromEntries(Object.keys({ ...common, ...specific }).map(name => [name, []])),
      optional: Object.fromEntries(['model', 'clip', 'vae', 'audio_vae', 'image', 'video', 'audio', 'sigmas',
        'second_model', 'face_model', 'previous_video', 'face_sigmas', 'guide_video', 'guide_image', 'guide_audio'].map(name => [name, []])),
    } } },
    removeInput(index) { this.inputs.splice(index, 1) },
    addCustomWidget(widget) { this.widgets.push(widget); return widget },
    computeSize() { return [460, 1000] }, setDirtyCanvas() {}, setSize(size) { this.size = size },
  }
  extension.nodeCreated(node)
  const widgets = new Map(node.widgets.map(w => [w.name, w]))
  const change = (name, value) => { const w = widgets.get(name); w.value = value; w.callback?.(value) }
  for (const name of ['second_model', 'face_model', 'previous_video', 'guide_video', 'guide_image', 'guide_audio']) {
    assert.equal(node.inputs.find(i => i.name === name).widget.name, name)
    assert.equal(widgets.get(name).serialize, false)
  }
  for (const name of ['model', 'clip', 'vae', 'audio_vae', 'image', 'video', 'audio', 'sigmas']) {
    assert.equal(node.inputs.find(i => i.name === name).widget, undefined)
    assert.equal(widgets.has(name), false)
  }
  assert.equal(node.inputs.find(i => i.name === 'sigmas').label, '自定义 Sigma')
  for (const [name, label] of [['image', '图片列表'], ['video', '视频列表'], ['audio', '音频列表']]) {
    assert.equal(node.inputs.find(i => i.name === name).shape, 6)
    assert.equal(node.inputs.find(i => i.name === name).label, label)
  }
  assert.equal(widgets.get('h3_context_length').value, 22)
  assert.equal(widgets.get('h3_context_length').serialize, false)
  const guideStart = node.widgets.findIndex(w => w.name === 'h3_section_Add Guide')
  const guideEnd = node.widgets.length
  for (const name of ['enable_add_guide', 'guide_video', 'guide_image', 'guide_audio', 'guide_frame_idx'])
    assert.ok(node.widgets.slice(guideStart, guideEnd).includes(widgets.get(name)))
  assert.equal(widgets.get('guide_frame_idx').disabled, true)
  change('enable_add_guide', true)
  assert.equal(widgets.get('guide_frame_idx').disabled, false)
  change('guide_frame_idx', -22)
  node.onConfigure()
  assert.equal(widgets.get('guide_frame_idx').value, -22)
  change('enable_add_guide', false)
  assert.equal(widgets.get('guide_frame_idx').disabled, true)
  const contextStart = node.widgets.findIndex(w => w.name === 'h3_section_分段上下文')
  const contextEnd = node.widgets.length
  assert.ok(node.widgets.slice(contextStart, contextEnd).includes(widgets.get('previous_video')))
  assert.equal(widgets.has('clip_index'), false)
  assert.ok(node.widgets.slice(contextStart, contextEnd).includes(widgets.get('context_auto_extend')))
  assert.equal(widgets.get('context_auto_extend').label, '自动增加22帧时长')
  assert.equal(widgets.get('context_auto_extend').disabled, true)
  assert.ok(node.widgets.slice(contextStart, contextEnd).includes(widgets.get('debug_keep_context')))
  assert.equal(widgets.get('debug_keep_context').label, '不裁剪上下文（调试）')
  assert.equal(widgets.get('debug_keep_context').disabled, true)
  change('enable_context', true)
  assert.equal(widgets.get('context_auto_extend').disabled, false)
  assert.equal(widgets.get('debug_keep_context').disabled, false)
  change('debug_keep_context', true)
  assert.equal(widgets.get('debug_keep_context').value, true)
  change('context_auto_extend', false)
  assert.equal(widgets.get('duration').label, '片段总时长（含上下文） / 秒')
  change('enable_context', false)
  assert.equal(widgets.get('context_auto_extend').disabled, true)
  assert.equal(widgets.get('debug_keep_context').disabled, true)
  node.inputs.push({ name: 'undeclared_model', label: '主模型', type: 'MODEL' },
    { name: 'model', label: '主模型', type: 'MODEL' })
  node.onConfigure()
  assert.equal(node.inputs.some(i => i.name === 'undeclared_model'), false)
  assert.equal(node.inputs.filter(i => i.name === 'model').length, 1)
  for (const [name, label] of [['context_noise_strength', '前 21 帧噪声强度'], ['context_color_strength', '接续调色强度']]) {
    assert.ok(node.widgets.slice(contextStart, contextEnd).includes(widgets.get(name)))
    assert.equal(widgets.get(name).label, label)
    change(name, 0.23)
    assert.equal(widgets.get(name).value, 0.23)
  }
  assert.equal(widgets.get('width').label, '最终宽度')
  assert.equal(widgets.get('height').label, '最终高度')
  assert.equal(node.widgets.filter(w => w.name.startsWith('face_') && w.type !== 'h3_input').map(w => w.name).join(','),
    'face_refine,face_count,face_sigmas,face_reverse')
  change('face_refine', true)
  for (const name of ['face_count', 'face_sigmas', 'face_reverse']) assert.equal(widgets.get(name).disabled, false)
  change('mode', '复刻模式'); assert.ok(widgets.get('duration').disabled)
  change('mode', '普通模式'); assert.equal(widgets.get('duration').disabled, false)
  node.inputs.find(i => i.name === 'sigmas').link = 9
  node.onConnectionsChange()
  for (const name of ['steps', 'scheduler', 'denoise']) assert.ok(widgets.get(name).disabled)
  node.inputs.find(i => i.name === 'previous_video').link = 10
  node.onConnectionsChange()
  assert.equal(widgets.get('enable_context').value, false)
  if (widgets.has('second_sigma_values')) {
    change('second_sigma_values', '0.4, 0.2, 0')
    for (const name of ['second_steps', 'second_sigma_start', 'second_rho']) assert.ok(widgets.get(name).disabled)
    change('second_sigma_values', '')
    for (const name of ['second_steps', 'second_sigma_start', 'second_rho']) assert.equal(widgets.get(name).disabled, false)
  }
  if (comfyClass === 'YtonH3VideoContextOmniGenerate') {
    assert.equal(widgets.get('first_pass_scale').value, 0.5)
    assert.ok(widgets.get('first_pass_scale').disabled)
    assert.equal(widgets.get('first_pass_scale').serialize, false)
    change('film_method', 'bicubic')
    assert.equal(widgets.get('film_match_stats').label, '统计匹配 / match_stats')
    assert.equal(widgets.has('selflift_transition_step'), false)
  } else {
    assert.equal(widgets.get('first_pass_scale').disabled, false)
    assert.equal(widgets.has('film_model'), false)
  }
  const sectionStart = node.widgets.findIndex(w => w.name === 'h3_section_二采方案')
  const sectionEnd = node.widgets.findIndex(w => w.name === 'h3_section_小脸修复')
  const secondWidgets = node.widgets.slice(sectionStart, sectionEnd)
  change('sampling_mode', '单采')
  assert.ok(secondWidgets.every(w => w.hidden && w.type === 'hidden'))
  assert.equal(widgets.get('h3_context_length').hidden, undefined)
  node.onConfigure()
  assert.ok(secondWidgets.every(w => w.hidden))
  change('sampling_mode', '二采')
  assert.ok(secondWidgets.every(w => w.hidden === false))
  assert.equal(widgets.get('sampler_name').disabled, comfyClass === 'YtonH3SelfLiftOmniGenerate')
}
const removed = { comfyClass: 'YtonH3OmniGenerate' }
extension.nodeCreated(removed)
assert.equal(removed.widgets, undefined)
console.log('H3 TR / SelfLift / traditional controls, mode switching, Sigma links and sections passed.')
