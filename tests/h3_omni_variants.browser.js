// Isolated browser regression: no generation, settings writes or workflow saves.
export async function runH3OmniVariants(page, definitions, examples, baseURL = 'http://127.0.0.1:8188') {
  const context = await page.context().browser().newContext({ viewport: { width: 1600, height: 1400 } })
  const p = await context.newPage()
  const errors = []
  p.on('pageerror', error => errors.push(error.message))
  await context.route('**/userdata/**', route => route.request().method() === 'GET' ? route.continue() : route.fulfill({ json: {} }))
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === 'POST' ? route.fulfill({ json: {} }) : route.continue())
  await context.route(/\/(?:api\/)?prompt$/, route => route.request().method() === 'POST' ? route.abort() : route.continue())
  try {
    await p.goto(baseURL)
    await p.getByTestId('workflows-tab-button').waitFor({ timeout: 60000 })
    await context.routeWebSocket('**/ws**', socket => socket.close())
    await p.evaluate(() => window.comfyAPI.api.api.socket?.close())
    const results = await p.evaluate(async ({ definitions, examples }) => {
      const assert = (condition, message) => { if (!condition) throw new Error(message) }
      const app = window.comfyAPI.app.app
      await app.registerNodesFromDefs(definitions)
      const results = []
      assert(!LiteGraph.registered_node_types.YtonH3OmniGenerate, 'old generator is not registered')
      for (const [type, definition] of Object.entries(definitions)) {
        const selflift = type === 'YtonH3SelfLiftOmniGenerate'
        const tr = type === 'YtonH3VideoContextOmniGenerate'
        await app.loadGraphData(examples[type])
        let node = app.graph._nodes.find(n => n.comfyClass === type)
        const id = node.id
        const w = name => node.widgets.find(w => w.name === name)
        const change = (name, value) => { const widget = w(name); widget.value = value; widget.callback?.(value) }
        const draw = async () => {
          app.canvas.ds.scale = 0.7
          app.canvas.ds.offset = [230 - node.pos[0], 180 - node.pos[1]]
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
          app.canvas.draw(true, true)
        }
        assert(node.title === definition.display_name, type + ' has requested title')
        assert(w('sampling_mode').value === '二采', type + ' defaults to progressive or second pass')
        assert(node.inputs.filter(i => !i.widget).map(i => i.name).join(',') === 'model_loader,image,video,audio,sigmas,previous_video', 'primary inputs stay at the top')
        assert(w('h3_context_length').value === 22 && w('h3_context_length').serialize === false, 'fixed context length stays visible')
        assert(w('sampling_plan').serialize === false, 'plan is display-only')
        assert(Boolean(w('film_model')) === tr && Boolean(w('selflift_transition_step')) === selflift, 'controls match the selected generator')
        assert(Boolean(w('second_sigma_values')) !== selflift, 'SelfLift uses only the main schedule')
        assert(w('first_pass_scale').disabled === tr, 'only TR fixes the first-pass scale')
        change('width', 1920); change('height', 1088)
        if (!tr) change('first_pass_scale', 0.5)
        if (selflift) { change('selflift_transition_step', 2); change('selflift_rho', 0.2) }
        const sigma = LiteGraph.createNode('ManualSigmas')
        app.graph.add(sigma)
        sigma.connect(0, node, node.findInputSlot('sigmas'))
        if (!selflift) sigma.connect(0, node, node.findInputSlot('second_sigma_values'))
        sigma.connect(0, node, node.findInputSlot('face_sigmas'))
        const media = app.graph.getNodeById(27)
        media.connect(1, node, node.findInputSlot('previous_video'))
        assert(w('enable_context').value === false, 'previous video does not enable context automatically')
        change('enable_context', true)
        change('context_noise_strength', 0.23)
        change('context_color_strength', 0.42)
        const contextControls = node.widgets.slice(
          node.widgets.findIndex(w => w.name === 'h3_section_分段上下文'),
          node.widgets.findIndex(w => w.name === 'h3_section_视频解码'))
        assert(contextControls.includes(w('context_noise_strength')) && contextControls.includes(w('context_color_strength')),
          'both controls appear in the context section')
        change('face_refine', true)
        app.graph.getNodeById(12).connect(0, node, node.findInputSlot('second_model'))
        const twoPassHeight = node.size[1]
        await draw()
        for (const [name, heading] of [['second_model', '二采方案'], ['face_model', '小脸修复']]) {
          const slot = node.findInputSlot(name)
          assert(node.getInputPos(slot)[1] > node.pos[1] + w('h3_section_' + heading).y, name + ' is in its section')
          assert(!w(name).connectionSuppressed, name + ' label is visible while connected')
        }
        change('sampling_mode', '单采')
        await draw()
        assert(node.size[1] < twoPassHeight - 100, 'single pass shrinks the node')
        assert(w('second_model').hidden && w('h3_section_二采方案').hidden, 'single pass hides the complete second-pass section')
        assert(Number.isNaN(node.getInputPos(node.findInputSlot('second_model'))[1]), 'hidden input has no hit target')
        const saved = app.graph.serialize()
        await app.loadGraphData(saved)
        node = app.graph.getNodeById(id)
        assert(w('sampling_mode').value === '单采' && w('second_model').hidden, 'visibility survives reload')
        change('sampling_mode', '二采')
        await draw()
        const prompt = (await app.graphToPrompt()).output[id]
        for (const name of ['model_loader', 'image', 'video', 'sigmas', 'second_model', 'face_model', 'previous_video', 'face_sigmas']) {
          assert(Array.isArray(prompt.inputs[name]), name + ' link survives reload')
        }
        assert(prompt.inputs.width === 1920 && prompt.inputs.height === 1088, 'final resolution survives reload')
        assert(prompt.inputs.context_noise_strength === 0.23 && prompt.inputs.context_color_strength === 0.42,
          'context noise and colour strengths survive reload and reach the API')
        assert(!('sampling_plan' in prompt.inputs) && !('h3_context_length' in prompt.inputs), 'display fields are not submitted')
        if (tr) assert(!('first_pass_scale' in prompt.inputs), 'TR fixed scale is not submitted')
        else assert(prompt.inputs.first_pass_scale === 0.5, 'editable scale is submitted')
        if (selflift) {
          assert(prompt.inputs.selflift_rho === 0.2 && prompt.inputs.selflift_transition_step === 2, 'SelfLift controls survive reload')
          assert(!('second_sigma_values' in prompt.inputs), 'SelfLift has no independent second Sigma')
        } else assert(Array.isArray(prompt.inputs.second_sigma_values), 'second Sigma survives reload')
        results.push({ type, title: node.title, size: [...node.size], checks: 'layout, links, save/reload, single pass, controls, API export' })
      }
      return results
    }, { definitions, examples })
    if (errors.length) throw new Error(errors.join('\n'))
    return results
  } finally {
    await context.close()
  }
}
