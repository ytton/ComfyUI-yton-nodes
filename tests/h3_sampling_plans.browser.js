// Run with a current Python INPUT_TYPES fixture; never submits a generation task.
export async function runH3SamplingBrowserRegression(page, schema, example, baseURL = 'http://127.0.0.1:8188') {
  const context = await page.context().browser().newContext({ viewport: { width: 1560, height: 1200 } })
  const p = await context.newPage()
  const errors = []
  p.on('pageerror', error => { if (/h3_omni_widgets/.test(error.stack || '')) errors.push(error.message) })
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch()
    const definitions = await response.json()
    if (definitions.YtonH3VideoContextOmniGenerate) Object.assign(definitions.YtonH3VideoContextOmniGenerate, schema)
    await route.fulfill({ response, json: definitions })
  })
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route =>
    route.request().method() === 'POST' ? route.fulfill({ json: {} }) : route.continue())
  await context.route('**/userdata/**', route =>
    route.request().method() === 'GET' ? route.continue() : route.fulfill({ json: {} }))
  await context.route(/\/(?:api\/)?prompt$/, route =>
    route.request().method() === 'POST' ? route.abort() : route.continue())
  try {
    await p.goto(baseURL + '/?h3-sampling-test=1')
    await p.getByTestId('workflows-tab-button').waitFor({ timeout: 60000 })
    const result = await p.evaluate(async example => {
      const assert = (condition, message) => { if (!condition) throw new Error(message) }
      const app = window.comfyAPI.app.app
      app.graph.clear()
      let node = LiteGraph.createNode('YtonH3VideoContextOmniGenerate')
      app.graph.add(node)
      node.pos = [180, 70]
      const w = name => node.widgets.find(widget => widget.name === name)
      const change = (name, value) => { const widget = w(name); widget.value = value; widget.callback?.(value) }
      assert(w('sampling_mode').value === '二采', 'new node defaults to Film second pass')
      assert(w('sampling_plan').value === 'Film 2×' && w('sampling_plan').disabled, 'Film method is visible and fixed')
      assert(w('first_pass_scale').value === 0.5 && w('first_pass_scale').disabled, 'half-size ratio is visible and fixed')
      assert(!w('upscale_model') && !w('selflift_transition_step'), 'only Film model controls are present')
      for (const name of ['film_method', 'film_model', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
        assert(w(name) && !w(name).disabled, name + ' is editable')
        assert(node.widgets.indexOf(w(name)) > node.widgets.findIndex(w => w.name === 'h3_section_二采方案'), name + ' is below second-pass heading')
        assert(node.widgets.indexOf(w(name)) < node.widgets.findIndex(w => w.name === 'h3_section_小脸修复'), name + ' is above face heading')
      }
      assert(w('film_audio_denoise').value === 0, 'audio stays locked by default')
      change('film_method', 'bicubic'); change('film_audio_denoise', 1)
      change('film_noise_resample', 'upscale'); change('film_match_stats', 0.65)
      assert(!w('film_match_stats').label.includes('忽略'), 'interpolation enables statistics matching')
      change('width', 1920); change('height', 1088)
      const id = node.id
      const saved = app.graph.serialize()
      await app.loadGraphData(saved)
      node = app.graph.getNodeById(id)
      let prompt = (await app.graphToPrompt()).output[id]
      assert(prompt.inputs.width === 1920 && prompt.inputs.height === 1088, 'final dimensions survive reload')
      assert(w('first_pass_scale').disabled && w('first_pass_scale').value === 0.5, 'fixed display survives reload')
      assert(!('sampling_plan' in prompt.inputs) && !('first_pass_scale' in prompt.inputs), 'display-only values are not submitted')
      assert(prompt.inputs.film_model === 'h3_clean_latent_upscaler_film_epoch200.safetensors', 'Film model survives reload')
      assert(prompt.inputs.film_method === 'bicubic' && prompt.inputs.film_audio_denoise === 1, 'method and audio settings survive reload')
      assert(prompt.inputs.film_noise_resample === 'upscale' && prompt.inputs.film_match_stats === 0.65, 'noise and statistics settings survive reload')
      const audioInput = node.inputs.find(input => input.name === 'film_audio_denoise')
      assert(audioInput?.widget?.name === 'film_audio_denoise', 'audio setting uses native widget socket')
      const audioSource = LiteGraph.createNode('PrimitiveFloat')
      app.graph.add(audioSource)
      audioSource.connect(0, node, node.findInputSlot('film_audio_denoise'))
      assert(Array.isArray((await app.graphToPrompt()).output[id].inputs.film_audio_denoise), 'audio setting accepts external control')
      node.disconnectInput(node.findInputSlot('film_audio_denoise'))
      app.graph.remove(audioSource)
      assert(node.findInputSlot('second_sigmas') === -1, 'no duplicate second-pass input')
      const secondInput = node.inputs.find(input => input.name === 'second_sigma_values')
      const faceInput = node.inputs.find(input => input.name === 'face_sigmas')
      assert(secondInput.widget?.name === 'second_sigma_values', 'second Sigma socket belongs to its lower widget')
      assert(faceInput.widget?.name === 'face_sigmas', 'face Sigma socket belongs to its lower widget')
      assert(node.widgets.indexOf(w('face_sigmas')) > node.widgets.findIndex(w => w.name === 'h3_section_小脸修复'), 'face Sigma is in face section')
      const textSource = LiteGraph.createNode('PrimitiveString')
      app.graph.add(textSource)
      textSource.connect(0, node, node.findInputSlot('second_sigma_values'))
      assert(Array.isArray((await app.graphToPrompt()).output[id].inputs.second_sigma_values), 'same control accepts external STRING')
      node.disconnectInput(node.findInputSlot('second_sigma_values'))
      app.graph.remove(textSource)
      const sigmas = LiteGraph.createNode('ManualSigmas')
      app.graph.add(sigmas)
      sigmas.connect(0, node, node.findInputSlot('second_sigma_values'))
      assert(w('second_sigma_values').disabled, 'connected Sigma disables the text source')
      prompt = (await app.graphToPrompt()).output[id]
      assert(Array.isArray(prompt.inputs.second_sigma_values), 'Sigma link is exported')
      change('sampling_mode', '单采')
      assert(w('film_model').disabled && w('second_sampler').disabled, 'single pass disables second-pass controls')
      for (const name of ['film_method', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
        assert(w(name).disabled, 'single pass disables ' + name)
      }
      change('face_refine', true)
      sigmas.connect(0, node, node.findInputSlot('face_sigmas'))
      assert(w('face_steps').disabled && w('face_denoise').disabled, 'connected face Sigma replaces face scheduler')
      prompt = (await app.graphToPrompt()).output[id]
      assert(Array.isArray(prompt.inputs.face_sigmas), 'face Sigma link exports from lower control')
      node.disconnectInput(node.findInputSlot('face_sigmas'))
      change('face_sigmas', '0.615, 0')
      assert(w('face_steps').disabled, 'manual face Sigma replaces face scheduler')
      change('face_sigmas', '')
      assert(!w('face_steps').disabled && !w('face_denoise').disabled, 'empty face Sigma restores scheduler')
      node.disconnectInput(node.findInputSlot('second_sigma_values'))
      app.graph.remove(sigmas)
      change('sampling_mode', '二采')
      assert(!w('second_sampler').disabled && !w('film_model').disabled, 'Film controls enable again')

      await app.loadGraphData(example)
      node = app.graph._nodes.find(node => node.comfyClass === 'YtonH3VideoContextOmniGenerate')
      prompt = (await app.graphToPrompt()).output[node.id]
      assert(prompt.inputs.width === 1920 && prompt.inputs.height === 1088, 'shipped example has final dimensions')
      assert(prompt.inputs.sampling_mode === '二采' && prompt.inputs.face_refine === true, 'example widget ordering matches schema')
      assert(prompt.inputs.film_model === 'h3_clean_latent_upscaler_film_epoch200.safetensors', 'example selects Film')
      assert(prompt.inputs.film_method === 'learned model' && prompt.inputs.film_audio_denoise === 0, 'example keeps default method and audio')
      assert(prompt.inputs.film_noise_resample === 'independent' && prompt.inputs.film_match_stats === 0, 'example keeps default noise and statistics')
      assert(Array.isArray(prompt.inputs.second_sigma_values) && Array.isArray(prompt.inputs.face_sigmas), 'example Sigma links target lower controls')
      assert(typeof prompt.inputs.seed === 'number' && prompt.inputs.clip_index === 1, 'seed and clip index remain aligned')
      assert(!('upscale_model' in prompt.inputs) && !('sampling_plan' in prompt.inputs), 'example has only current inputs')
      return { checks: ['Film default', 'visible fixed ratio', 'native save/reload', 'final dimensions',
        'display values excluded from API', 'unified STRING/SIGMAS control', 'face Sigma control and blank schedule',
        'single pass', 'Film parameter editing, links and reload', 'shipped example Sigma links'],
        size: [...node.size] }
    }, example)
    if (errors.length) throw new Error(errors.join('\n'))
    return result
  } finally {
    await context.close()
  }
}
