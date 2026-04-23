"""YAML loader with CloudFormation intrinsic function support."""

import yaml


def _cfn_tag_constructor(loader, tag_suffix, node):
    """Handle any CloudFormation intrinsic function tag."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


# Build a custom loader that handles all !Tag intrinsics
CfnLoader = type("CfnLoader", (yaml.SafeLoader,), {})
CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)


def load_yaml(text: str):
    """Load YAML text with CloudFormation intrinsic function support."""
    return yaml.load(text, Loader=CfnLoader)
