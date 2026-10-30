// Run on an isolated ComfyUI page using the current Python object_info schema.
async (page) => {
  const p=page.context().browser().contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('h3-sampling-test=1'));
  if (!p) throw new Error('Open the isolated current-schema test page first');
  return await p.evaluate(async()=>{
    const assert=(condition,message)=>{if(!condition)throw new Error(message)};
    const app=window.comfyAPI.app.app;
    app.graph.clear();
    let node=LiteGraph.createNode('YtonH3VideoContextOmniGenerate');
    app.graph.add(node);node.pos=[180,70];
    await new Promise(resolve=>requestAnimationFrame(resolve));
    const w=name=>node.widgets.find(w=>w.name===name);
    const change=(name,value)=>{const widget=w(name);widget.value=value;widget.callback?.(value);};
    change('sampling_mode','二采');change('first_pass_scale',0.7);
    change('sampling_plan','Film 2×');
    assert(w('first_pass_scale').value===0.5 && w('first_pass_scale').disabled,'Film ratio must be visible, fixed and disabled');
    assert(w('upscale_model').disabled && !w('film_model').disabled,'Film has its own model');
    change('width',1920);change('height',1088);
    const id=node.id;
    const saved=app.graph.serialize();
    await app.loadGraphData(saved);
    node=app.graph.getNodeById(id);
    let prompt=(await app.graphToPrompt()).output[id];
    assert(prompt.inputs.sampling_plan==='Film 2×','Plan must survive workflow reload');
    assert(prompt.inputs.width===1920 && prompt.inputs.height===1088,'Final dimensions must survive workflow reload');
    assert(prompt.inputs.first_pass_scale===0.5,'Fixed ratio must survive reload and export');
    assert(prompt.inputs.film_model==='h3_clean_latent_upscaler_film_epoch200.safetensors','Film model must survive reload');
    change('sampling_plan','SelfLift Progressive Sampler (MiniMax H3)');
    change('first_pass_scale',0.6);change('selflift_transition_step',2);
    assert(w('sampler_name').value==='euler' && w('sampler_name').disabled,'SelfLift uses Euler');
    assert(w('second_sigma_values').disabled && w('second_sampler').disabled,'SelfLift uses the complete main schedule');
    const sigmas=LiteGraph.createNode('ManualSigmas');app.graph.add(sigmas);
    sigmas.connect(0,node,node.findInputSlot('second_sigmas'));
    prompt=(await app.graphToPrompt()).output[id];
    assert(prompt.inputs.first_pass_scale===0.6 && prompt.inputs.selflift_transition_step===2,'SelfLift controls export');
    change('sampling_plan','传统二采');
    assert(!w('first_pass_scale').disabled && !w('second_sampler').disabled,'Traditional controls stay adjustable');
    assert(w('second_sigma_values').disabled,'Connected Sigma disables only the text source');
    change('sampling_mode','单采');
    assert(w('sampling_plan').disabled && w('first_pass_scale').disabled,'Single pass disables second pass options');
    // Leave the result on Film for visual review.
    node.disconnectInput(node.findInputSlot('second_sigmas'));
    app.graph.remove(sigmas);
    change('sampling_mode','二采');change('sampling_plan','Film 2×');
    app.canvas.ds.scale=0.75;app.canvas.ds.offset=[80,20];app.canvas.setDirty(true,true);
    window.history.replaceState(null,'','/?h3-sampling-test=1');
    return {checks:['Film fixed scale','native workflow save/reload','final dimensions','Sigma connections',
      'SelfLift Euler and controls','traditional adjustable scale','single pass'],widgets:node.widgets.length,
      prompt:(await app.graphToPrompt()).output[id]};
  });
}
