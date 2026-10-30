// Build examples with native widget serialization and canonical input indices.
export async function buildH3OmniVariants(page, definitions, template, baseURL = 'http://127.0.0.1:8188') {
  const context = await page.context().browser().newContext({ viewport: { width: 1600, height: 1400 } })
  await context.route(/\/(?:api\/)?object_info(?:\/[^?]+)?(?:\?.*)?$/, async route => {
    const response = await route.fetch()
    const data = await response.json()
    delete data.YtonH3OmniGenerate
    Object.assign(data, definitions)
    await route.fulfill({ response, json: data })
  })
  await context.route('**/userdata/**', route => route.request().method() === 'GET' ? route.continue() : route.fulfill({ json: {} }))
  await context.route(/\/(?:api\/)?settings(?:\/|$)/, route => route.request().method() === 'POST' ? route.fulfill({ json: {} }) : route.continue())
  await context.route(/\/(?:api\/)?prompt$/, route => route.request().method() === 'POST' ? route.abort() : route.continue())
  const p = await context.newPage()
  try {
    await p.goto(baseURL)
    await p.getByTestId('workflows-tab-button').waitFor({ timeout: 60000 })
    return await p.evaluate(async ({ definitions, template }) => {
      const app = window.comfyAPI.app.app
      const source = template.nodes.find(n => n.type === 'YtonH3VideoContextOmniGenerate')
      const result = {}
      for (const [type, definition] of Object.entries(definitions)) {
        const data = structuredClone(template)
        data.nodes = data.nodes.filter(n => n.id !== source.id)
        const incident = data.links.filter(link => link[1] === source.id || link[3] === source.id)
        const ids = new Set(incident.map(link => link[0]))
        data.links = data.links.filter(link => !ids.has(link[0]))
        for (const n of data.nodes) {
          for (const input of n.inputs || []) if (ids.has(input.link)) input.link = null
          for (const output of n.outputs || []) if (output.links) output.links = output.links.filter(id => !ids.has(id))
          if (n.type === 'Note' && /视频上下文/.test(n.title || '')) {
            n.widgets_values = ['三种方案共用可选视频上下文。首段关闭上下文；续段连接上一段视频并打开开关。自动增加与裁除 22 帧，输出填写时长。SelfLift 共用主采完整 Sigma，切换步数须小于总步数。']
          }
        }
        await app.loadGraphData(data)
        const node = LiteGraph.createNode(type)
        node.id = source.id
        node.pos = [...source.pos]
        node.title = definition.display_name
        app.graph.add(node)
        const named = { ...source.widgets_values_named, duration: 5, face_refine: false }
        for (const w of node.widgets) {
          if (w.serialize === false || !(w.name in named)) continue
          if (['second_sampler', 'second_sigma_values', 'first_pass_scale', 'sampler_name'].includes(w.name)) continue
          w.value = named[w.name]
          w.callback?.(w.value)
        }
        for (const link of incident) {
          if (link[3] === source.id) {
            const name = source.inputs[link[4]].name
            // The example starts with the internal face schedule and no main override.
            if (name === 'face_sigmas') continue
            const slot = node.findInputSlot(name)
            if (slot !== -1) app.graph.getNodeById(link[1]).connect(link[2], node, slot)
          } else {
            node.connect(link[2], app.graph.getNodeById(link[3]), link[4])
          }
        }
        node.setSize([620, node.computeSize()[1]])
        const workflow = app.graph.serialize()
        const saved = workflow.nodes.find(n => String(n.id) === String(node.id))
        saved.widgets_values_named = Object.fromEntries(node.widgets.filter(w => w.serialize !== false).map(w => [w.name, w.value]))
        result[type] = workflow
      }
      return result
    }, { definitions, template })
  } finally {
    await context.close()
  }
}
