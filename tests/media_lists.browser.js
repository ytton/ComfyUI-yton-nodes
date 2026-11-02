// Isolated frontend checks: never submit a generation or save user workflows.
export async function runMediaLists(page, definitions, baseURL = 'http://127.0.0.1:8188') {
  const context = await page.context().browser().newContext({ viewport: { width: 1500, height: 1100 } })
  const p = await context.newPage()
  await context.route('**/userdata/**', route => route.request().method() === 'GET' ? route.continue() : route.fulfill({ json: {} }))
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === 'POST' ? route.fulfill({ json: {} }) : route.continue())
  await context.route(/\/(?:api\/)?prompt$/, route => route.request().method() === 'POST' ? route.abort() : route.continue())
  try {
    await p.goto(baseURL)
    await p.getByTestId('workflows-tab-button').waitFor({ timeout: 60000 })
    await p.waitForFunction(() => {
      const app = window.comfyAPI?.app?.app
      return app?.vueAppReady && app.graphLoadSequence > 0 &&
        app.committedGraphLoadSequence === app.graphLoadSequence && app.pendingGraphLoads.size === 0
    })
    await context.routeWebSocket('**/ws**', socket => socket.close())
    const result = await p.evaluate(async definitions => {
      const app = window.comfyAPI.app.app
      window.comfyAPI.api.api.socket?.close()
      const assert = (value, message) => { if (!value) throw Error(message) }
      await app.registerNodesFromDefs(definitions)
      app.graph.clear()
      const target = LiteGraph.createNode('YtonH3TraditionalOmniGenerate')
      app.graph.add(target)
      target.pos = [850, 80]
      const results = []
      for (const [type, sourceType, kind, name, group, prefix] of [
        ['YtonImageToList', 'LoadImage', 'IMAGE', 'image', 'images', 'image_'],
        ['YtonVideoToList', 'LoadVideo', 'VIDEO', 'video', 'videos', 'video_'],
        ['YtonAudioToList', 'LoadAudio', 'AUDIO', 'audio', 'audios', 'audio_'],
      ]) {
        const collector = LiteGraph.createNode(type)
        app.graph.add(collector)
        collector.pos = [500, 80 + results.length * 200]
        assert(collector.outputs[0].shape === LiteGraph.GRID_SHAPE, type + ' outputs a list icon')
        for (let i = 0; i < 3; i++) {
          const source = LiteGraph.createNode(sourceType)
          app.graph.add(source)
          source.pos = [50, 80 + results.length * 200 + i * 40]
          if (i === 0) {
            source.connect(0, target, target.findInputSlot(name))
            assert(target.inputs[target.findInputSlot(name)].link != null, kind + ' single media connects directly')
          }
          const inputName = `${group}.${prefix}${i}`
          assert(collector.findInputSlot(inputName) >= 0, type + ' exposes the next input')
          source.connect(0, collector, collector.findInputSlot(inputName))
        }
        assert(collector.inputs.filter(i => i.link != null).length === 3, type + ' keeps three sources')
        assert(collector.inputs.some(i => i.name === `${group}.${prefix}3`), type + ' grows a fourth input')
        collector.connect(0, target, target.findInputSlot(name))
        const inputs = (await app.graphToPrompt()).output[collector.id].inputs
        for (let i = 0; i < 3; i++) assert(Array.isArray(inputs[`${group}.${prefix}${i}`]), type + ' exports each source')
        results.push({ id: collector.id, type, kind, count: 3 })
      }
      const saved = app.graph.serialize()
      await app.loadGraphData(saved)
      for (const { id, type } of results) {
        const collector = app.graph.getNodeById(id)
        assert(collector.inputs.filter(i => i.link != null).length === 3, type + ' preserves sources after reload')
        assert(collector.outputs[0].shape === LiteGraph.GRID_SHAPE, type + ' preserves the list icon')
      }
      return results
    }, definitions)
    return result
  } finally {
    await context.close()
  }
}
