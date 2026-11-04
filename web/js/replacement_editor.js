// Adapt our config to the embedded PGS editor's widget interface.
// Timeline, crop handles, previews and controls use the embedded reference implementation.
export async function openReplacementEditor(config, onApply) {
  const [{openVideoEditor}, {injectStyles}] = await Promise.all([
    import("./replacement/video_editor.js"),
    import("./replacement/video_editor_support.js"),
  ]);
  const draft=structuredClone(config), plan=draft.plan, compression=draft.compression;
  const fps=plan.enabled ? 24 : compression.fps;
  const [cx,cy,cw,ch]=draft.crop || [0,0,1,1];
  const values={filename:draft.video,display_mode:"seconds",
    start_time:plan.start,end_time:plan.end,duration:plan.end ? plan.end-plan.start : 0,
    start_frame:Math.round(plan.start*fps),end_frame:Math.round(plan.end*fps),
    duration_frames:plan.end ? Math.round((plan.end-plan.start)*fps) : 0,
    frame_rate:fps,custom_width:compression.width || 0,custom_height:compression.height || 0,
    resize_method:compression.resize_method || "pad",crop_x:cx,crop_y:cy,crop_w:cw,crop_h:ch,segment_plan_json:""};
  const properties={};
  if(plan.enabled) properties.segment_plan={
    preset:plan.mode==="MiniMax H3" ? "minimaxh3" : "none",
    target_seconds:plan.mode==="MiniMax H3" ? plan.frames/24 : plan.seconds,
    context_frames:plan.overlap,output_mode:plan.output==="完整片段" ? "raw" : "delivered",
    split:plan.split || "fixed", detector:plan.detector || "adaptive", sensitivity:plan.sensitivity ?? .5,
    min_seconds:plan.min_seconds ?? 1, cuts:plan.cuts, shot_source:plan.shot_source,
    segments:[{start:0,end:1}],
  };
  let applied=false;
  const adapter={
    widgets:Object.entries(values).map(([name,value])=>({name,value})),properties,
    setDirtyCanvas(){},
    _pgsVideoRender(){
      if(applied) return;
      applied=true;
      const value=name=>adapter.widgets.find(w=>w.name===name).value;
      const nativePlan=adapter.properties.segment_plan;
      Object.assign(plan,{enabled:!!nativePlan,start:Number(value("start_time")),end:Number(value("end_time"))});
      if(nativePlan) Object.assign(plan,{
        mode:nativePlan.preset==="minimaxh3" ? "MiniMax H3" : "普通",
        frames:Math.round(nativePlan.target_seconds*24),seconds:nativePlan.target_seconds,
        overlap:nativePlan.context_frames,output:nativePlan.output_mode==="raw" ? "完整片段" : "仅新增片段",
        split:nativePlan.split,detector:nativePlan.detector,sensitivity:nativePlan.sensitivity,
        min_seconds:nativePlan.min_seconds,cuts:nativePlan.cuts,shot_source:nativePlan.shot_source,
      });
      const crop=["crop_x","crop_y","crop_w","crop_h"].map(name=>Number(value(name)));
      draft.crop=crop.some((n,i)=>n!==[0,0,1,1][i]) ? crop : null;
      Object.assign(compression,{fps:Number(value("frame_rate")),width:Number(value("custom_width")),
        height:Number(value("custom_height")),resize_method:value("resize_method")});
      onApply(draft);
    },
  };
  injectStyles();
  openVideoEditor(adapter);
}
