"""分类与内部节点可见性。"""


def configure_node_catalog(classes):
    internal_nodes = {
        "YtonH3ReplicaPlan", "YtonH3SegmentPlan", "YtonH3SegmentTrim",
        "YtonH3LoadOmniContext", "YtonH3SaveOmniContext",
    }
    category_names = {"Resolution": "分辨率", "Logic": "逻辑", "Media": "媒体", "H3": "MiniMax H3"}
    for name, node in classes.items():
        category = getattr(node, "CATEGORY", "").split("/")
        if category[0] == "yton-nodes" and len(category) > 1:
            category[1] = category_names.get(category[1], category[1])
            node.CATEGORY = "/".join(category)
        if name in internal_nodes:
            node.CATEGORY = "yton-nodes/MiniMax H3/内部"
            node.DEV_ONLY = True
