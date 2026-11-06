import { app } from "../../../scripts/app.js";

export async function manualLLMConnection(node) {
  const link=node.graph?.links[node.inputs.find(input=>input.name==="llm")?.link];
  if(!link)throw new Error("请连接 LLM 通用连接器或本地模型连接器。");
  const {output}=await app.graphToPrompt();
  const source=output[String(link.origin_id)];
  const local=source?.class_type==="YtonLocalLLMConnector";
  if(!local&&source?.class_type!=="YtonLLMConnector")throw new Error("手动优化需要连接 LLM 通用连接器或本地模型连接器。");
  const keys=local?["model_name","options_json"]:["model_ref","temperature","max_tokens"];
  const values=Object.fromEntries(keys.map(key=>[key,source.inputs[key]]));
  if(Object.values(values).some(Array.isArray))throw new Error("连接器参数来自上游时，请开启自动优化执行工作流。");
  if(local&&!values.model_name)throw new Error("请先在本地模型连接器中选择 GGUF 模型。");
  return {kind:local?"local":"remote",...values};
}
