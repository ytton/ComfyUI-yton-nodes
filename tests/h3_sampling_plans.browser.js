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
      for (const name of ['film_method', 'film_model', 'film_ff_chunks', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
        assert(w(name) && !w(name).disabled, name + ' is editable')
        assert(node.widgets.indexOf(w(name)) > node.widgets.findIndex(w => w.name === 'h3_section_二采方案'), name + ' is below second-pass heading')
        assert(node.widgets.indexOf(w(name)) < node.widgets.findIndex(w => w.name === 'h3_section_小脸修复'), name + ' is above face heading')
      }
      assert(w('film_audio_denoise').value === 0, 'audio stays locked by default')
      assert(w('second_sigma_values').value === '', 'automatic second-pass schedule is the default')
      assert(w('second_sampler').value === 'euler', 'second pass defaults to non-ancestral Euler')
      assert(w('film_ff_chunks').value === '8', 'second pass limits feedforward memory by default')
      const faceControls = ['face_refine', 'face_count', 'face_sigmas', 'face_reverse']
      assert(JSON.stringify(node.widgets.filter(w => w.name.startsWith('face_')).map(w => w.name)) === JSON.stringify(faceControls), 'only four face controls remain')
      const internalFace = ['face_steps', 'face_denoise', 'face_large_strength', 'face_detector', 'face_fallback_detector', 'face_seed']
      assert(internalFace.every(name => !w(name) && node.findInputSlot(name) === -1), 'internal face settings have no widgets or sockets')
      const autoSecond = ['second_steps', 'second_sigma_start', 'second_rho']
      assert(autoSecond.every(name => !w(name).disabled), 'automatic controls are editable')
      change('second_sigma_values', '0.4, 0.2, 0')
      assert(autoSecond.every(name => w(name).disabled), 'manual schedule overrides automatic controls')
      change('second_sigma_values', '')
      change('second_steps', 6); change('second_sigma_start', 0.42); change('second_rho', 8)
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
      assert(prompt.inputs.second_steps === 6 && prompt.inputs.second_sigma_start === 0.42 && prompt.inputs.second_rho === 8, 'automatic schedule settings survive reload')
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
      assert(autoSecond.every(name => w(name).disabled), 'connected Sigma overrides automatic controls')
      prompt = (await app.graphToPrompt()).output[id]
      assert(Array.isArray(prompt.inputs.second_sigma_values), 'Sigma link is exported')
      const twoPassHeight = node.size[1]
      const secondWidgets = ['sampling_plan', 'first_pass_scale', 'film_method', 'film_model', 'film_ff_chunks',
        'film_audio_denoise', 'film_noise_resample', 'film_match_stats', 'second_sampler', 'second_sigma_values', ...autoSecond]
      change('sampling_mode', '单采')
      assert(secondWidgets.every(name => w(name).hidden), 'single pass hides every second-pass widget')
      assert(w('h3_section_二采方案').hidden, 'single pass hides second-pass heading')
      assert(node.size[1] < twoPassHeight - 200, 'single pass shrinks the node')
      assert(!w('h3_context_length').hidden, 'context frame count remains visible')
      assert(w('film_model').disabled && w('second_sampler').disabled, 'single pass disables second-pass controls')
      for (const name of ['film_method', 'film_audio_denoise', 'film_noise_resample', 'film_match_stats']) {
        assert(w(name).disabled, 'single pass disables ' + name)
      }
      change('face_refine', true)
      sigmas.connect(0, node, node.findInputSlot('face_sigmas'))
      prompt = (await app.graphToPrompt()).output[id]
      assert(Array.isArray(prompt.inputs.face_sigmas), 'face Sigma link exports from lower control')
      assert(internalFace.every(name => !(name in prompt.inputs)), 'internal face settings are not submitted')
      node.disconnectInput(node.findInputSlot('face_sigmas'))
      change('face_sigmas', '0.615, 0')
      assert((await app.graphToPrompt()).output[id].inputs.face_sigmas === '0.615, 0', 'manual face Sigma is exported')
      change('face_sigmas', '')
      assert((await app.graphToPrompt()).output[id].inputs.face_sigmas === '', 'empty face Sigma uses internal schedule')
      const singleSaved = app.graph.serialize()
      await app.loadGraphData(singleSaved)
      node = app.graph.getNodeById(id)
      assert(w('sampling_mode').value === '单采' && secondWidgets.every(name => w(name).hidden), 'single-pass visibility survives reload')
      assert(Array.isArray((await app.graphToPrompt()).output[id].inputs.second_sigma_values), 'hidden Sigma connection survives reload')
      node.disconnectInput(node.findInputSlot('second_sigma_values'))
      app.graph.remove(app.graph.getNodeById(sigmas.id))
      change('sampling_mode', '二采')
      assert(secondWidgets.every(name => !w(name).hidden), 'switching back restores second-pass controls')
      assert(w('second_steps').value === 6 && w('second_sigma_start').value === 0.42, 'switching preserves second-pass settings')
      assert(!w('second_sampler').disabled && !w('film_model').disabled, 'Film controls enable again')
      assert(autoSecond.every(name => !w(name).disabled), 'disconnect restores automatic schedule')

      await app.loadGraphData(example)
      node = app.graph._nodes.find(node => node.comfyClass === 'YtonH3VideoContextOmniGenerate')
      prompt = (await app.graphToPrompt()).output[node.id]
      assert(prompt.inputs.width === 1920 && prompt.inputs.height === 1088, 'shipped example has final dimensions')
      assert(prompt.inputs.sampling_mode === '二采' && prompt.inputs.face_refine === true, 'example widget ordering matches schema')
      assert(prompt.inputs.film_model === 'h3_clean_latent_upscaler_film_epoch200.safetensors', 'example selects Film')
      assert(prompt.inputs.film_method === 'learned model' && prompt.inputs.film_audio_denoise === 0, 'example keeps default method and audio')
      assert(prompt.inputs.film_noise_resample === 'independent' && prompt.inputs.film_match_stats === 0, 'example keeps default noise and statistics')
      assert(prompt.inputs.second_sigma_values === '' && prompt.inputs.second_steps === 4, 'example uses automatic second-pass schedule')
      assert(Array.isArray(prompt.inputs.face_sigmas), 'example face Sigma link targets lower control')
      assert(typeof prompt.inputs.seed === 'number' && prompt.inputs.clip_index === 1, 'seed and clip index remain aligned')
      assert(!('upscale_model' in prompt.inputs) && !('sampling_plan' in prompt.inputs), 'example has only current inputs')
      return { checks: ['Film default', 'visible fixed ratio', 'native save/reload', 'final dimensions',
        'display values excluded from API', 'unified STRING/SIGMAS control', 'face Sigma control and blank schedule',
        'single-pass hiding and reload', 'four face controls', 'Film parameter editing, links and reload', 'shipped example Sigma links'],
        size: [...node.size] }
    }, example)
    if (errors.length) throw new Error(errors.join('\n'))
    return result
  } finally {
    await context.close()
  }
}
