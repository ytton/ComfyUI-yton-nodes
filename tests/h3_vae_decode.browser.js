// Run in a separate context; all writes and GPU submissions are blocked.
export async function runH3VaeDecode(browser, definitions, baseURL = 'http://127.0.0.1:8188') {
  const context = await browser.newContext({ viewport: { width: 1500, height: 1300 } })
  const errors = []
  await context.route('**/*', async route => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(route.request().method())) return route.fulfill({ json: {} })
    if (new URL(route.request().url()).pathname.endsWith('/object_info')) {
      const response = await route.fetch()
      return route.fulfill({ response, json: { ...await response.json(), ...definitions } })
    }
    return route.continue()
  })
  try {
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(baseURL)
    await page.getByTestId('workflows-tab-button').waitFor({ timeout: 60000 })
    await page.waitForFunction(() => window.comfyAPI?.app?.app?.canvas?.canvas?.isConnected)
    const results = await page.evaluate(async definitions => {
      const app = window.comfyAPI.app.app
      const assert = (condition, message) => { if (!condition) throw new Error(message) }
      const results = []
      for (const type of Object.keys(definitions)) {
        await app.loadGraphData({ version: 0.4, nodes: [], links: [], groups: [], config: {}, extra: {} })
        let node = LiteGraph.createNode(type)
        node.pos = [200, 100]
        app.graph.add(node)
        const id = node.id
        const widget = name => node.widgets.find(w => w.name === name)
        const change = (name, value) => { const w = widget(name); w.value = value; w.callback?.(value) }
        const payload = async () => (await app.graphToPrompt()).output[id].inputs
        assert(widget('vae_decode_mode').value === '标准解码', type + ': standard default')
        assert(widget('vae_decode_mode').options.values.join(',') === '标准解码,X2 VAE 解码', type + ': decode choices')
        assert(widget('x2_vae_name').hidden && widget('vae_tile_size').hidden, type + ': inactive controls hidden')
        const originalSize = [...node.size]
        change('width', 1344)
        change('height', 768)
        change('vae_decode_mode', 'X2 VAE 解码')
        change('vae_tile_size', 512)
        change('vae_tile_overlap', 128)
        assert(!widget('x2_vae_name').hidden, type + ': X2 weights visible')
        assert(widget('width').label === '采样画布宽度（成片 ×2）', type + ': explicit output scale')
        assert(widget('width').value === 1344 && widget('height').value === 768, type + ': canvas unchanged')
        assert(widget('sampling_mode').value === '二采', type + ': sampling plan unchanged')
        const sigma = LiteGraph.createNode('ManualSigmas')
        app.graph.add(sigma)
        sigma.connect(0, node, node.findInputSlot('sigmas'))
        change('sampling_mode', '单采')
        assert(widget('second_model').hidden, type + ': single pass hides second-pass options')
        assert(!widget('vae_tile_size').hidden, type + ': decoder independent of pass count')
        const first = await payload()
        const saved = app.graph.serialize()
        await app.loadGraphData(saved)
        node = app.graph.getNodeById(id)
        const reloaded = await payload()
        for (const value of [first, reloaded]) {
          assert(value.vae_decode_mode === 'X2 VAE 解码', type + ': decode mode serialized')
          assert(value.x2_vae_name.toLowerCase().includes('minimax-h3-x2-detail'), type + ': local X2 default')
          assert(value.vae_tile_size === 512 && value.vae_tile_overlap === 128, type + ': tile settings serialized')
          assert(value.width === 1344 && value.height === 768, type + ': no canvas rewrite')
          assert(Array.isArray(value.sigmas), type + ': sigma connection preserved')
          assert(value.sampling_mode === '单采', type + ': pass count serialized')
        }
        assert(!widget('x2_vae_name').hidden, type + ': X2 controls survive reload')
        change('vae_decode_mode', '标准解码')
        assert(widget('x2_vae_name').hidden && widget('vae_tile_size').hidden, type + ': hide controls on return')
        assert(widget('width').label === '最终宽度', type + ': normal label restored')
        change('sampling_mode', '二采')
        assert(!widget('second_model').hidden, type + ': second pass independent')
        change('vae_decode_mode', 'X2 VAE 解码')
        node.setSize([620, node.computeSize()[1]])
        app.canvas.ds.scale = 0.9
        app.canvas.ds.offset = [50, 520 - node.pos[1] - widget('h3_section_视频解码').y]
        app.canvas.setDirty(true, true)
        results.push({ type, originalSize, size: [...node.size], settings: reloaded })
      }
      return results
    }, definitions)
    if (errors.length) throw new Error(errors.join('\n'))
    return { results, screenshot: await page.screenshot() }
  } finally {
    await context.close()
  }
}
