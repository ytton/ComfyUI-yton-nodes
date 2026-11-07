import { getWidgetConfig } from "../../../extensions/core/widgetInputs.js";

export function comboChoices(input) {
  const [type, config] = getWidgetConfig(input);
  return Array.isArray(type) ? type : config?.options;
}

export function comboTargets(node, slot = 0) {
  return (node.outputs[slot]?.links || []).map(id => {
    const link = node.graph.links[id];
    const target = node.graph.getNodeById(link.target_id);
    return { target, input: target.inputs[link.target_slot] };
  });
}

export function commonComboChoices(connections) {
  const lists = connections.map(({ input }) => comboChoices(input));
  if (!lists.length || lists.some(values => !Array.isArray(values))) return [];
  return lists[0].filter(value => lists.every(values => values.includes(value)));
}
