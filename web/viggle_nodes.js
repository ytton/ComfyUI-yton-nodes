import { app } from "../../scripts/app.js";
import { setupVigglePanel } from "./js/viggle_panel.js";

const css=document.createElement("link");css.rel="stylesheet";css.href=new URL("css/viggle.css",import.meta.url).href;document.head.append(css);

app.registerExtension({
  name:"yton.viggle-replacement",
  async beforeRegisterNodeDef(nodeType,nodeData) {
    if(nodeData.name==="YtonViggleReplacementPlan") {
      const created=nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated=function(){created?.apply(this,arguments);setupVigglePanel(this);};
    }
    if(nodeData.name==="YtonViggleReplacementSegment") {
      const executed=nodeType.prototype.onExecuted;
      nodeType.prototype.onExecuted=function(data){
        executed?.apply(this,arguments);
        const link=this.graph?.links[this.inputs.find(input=>input.name==="plan")?.link];
        const parent=link&&this.graph.getNodeById(link.origin_id);
        if(parent?.type==="YtonViggleReplacementPlan")parent.onExecuted?.(data);
      };
    }
  },
});
