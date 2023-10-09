# Copyright 2018-2022 The glTF-Blender-IO authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from . import gltf2_blender_gather_texture_info
from .gltf2_blender_search_node_tree import \
    get_socket, \
    NodeSocket, \
    previous_socket, \
    previous_node, \
    get_factor_from_socket

def detect_shadeless_material(blender_material, export_settings):
    """Detect if this material is "shadeless" ie. should be exported
    with KHR_materials_unlit. Returns None if not. Otherwise, returns
    a dict with info from parsing the node tree.
    """
    if not blender_material.use_nodes: return None

    # Old Background node detection (unlikely to happen)
    bg_socket = get_socket(blender_material, "Background")
    if bg_socket.socket is not None:
        return {'rgb_socket': bg_socket}

    # Look for
    # * any color socket, connected to...
    # * optionally, the lightpath trick, connected to...
    # * optionally, a mix-with-transparent (for alpha), connected to...
    # * the output node

    info = {}

    #TODOSNode this can be a function call
    for node in blender_material.node_tree.nodes:
        if node.type == 'OUTPUT_MATERIAL' and node.is_active_output:
            socket = node.inputs[0]
            break
    else:
        return None

    socket = NodeSocket(socket, [])

    # Be careful not to misidentify a lightpath trick as mix-alpha.
    result = __detect_lightpath_trick(socket)
    if result is not None:
        socket = result['next_socket']
    else:
        result = __detect_mix_alpha(socket)
        if result is not None:
            socket = result['next_socket']
            info['alpha_socket'] = result['alpha_socket']

        result = __detect_lightpath_trick(socket)
        if result is not None:
            socket = result['next_socket']

    # Check if a color socket, or connected to a color socket
    if socket.socket.type != 'RGBA':
        from_socket = previous_socket(socket)
        if from_socket.socket is None: return None
        if from_socket.socket.type != 'RGBA': return None

    info['rgb_socket'] = socket
    return info


def __detect_mix_alpha(socket):
    # Detects this (used for an alpha hookup)
    #
    #                  [   Mix   ]
    #  alpha_socket => [Factor   ] => socket
    # [Transparent] => [Shader   ]
    #   next_socket => [Shader   ]
    #
    # Returns None if not detected. Otherwise, a dict containing alpha_socket
    # and next_socket.
    prev = previous_node(socket)
    if prev.node is None or prev.node.type != 'MIX_SHADER': return None
    in1 = previous_node(NodeSocket(prev.node.inputs[1], prev.group_path))
    if in1.node is None or in1.node.type != 'BSDF_TRANSPARENT': return None
    return {
        'alpha_socket': NodeSocket(prev.node.inputs[0], prev.group_path),
        'next_socket': NodeSocket(prev.node.inputs[2], prev.group_path),
    }


def __detect_lightpath_trick(socket):
    # Detects this (used to prevent casting light on other objects) See ex.
    # https://blender.stackexchange.com/a/21535/88681
    #
    #                 [   Lightpath  ]    [    Mix    ]
    #                 [ Is Camera Ray] => [Factor     ] => socket
    #                     (don't care) => [Shader     ]
    #      next_socket => [ Emission ] => [Shader     ]
    #
    # The Emission node can be omitted.
    # Returns None if not detected. Otherwise, a dict containing
    # next_socket.
    prev = previous_node(socket)
    if prev.node is None or prev.node.type != 'MIX_SHADER': return None
    in0 = previous_socket(NodeSocket(prev.node.inputs[0], prev.group_path))
    if in0.socket is None or in0.socket.node.type != 'LIGHT_PATH': return None
    if in0.socket.name != 'Is Camera Ray': return None
    next_socket = NodeSocket(prev.node.inputs[2], prev.group_path)

    # Detect emission
    prev = previous_node(next_socket)
    if prev.node is not None and prev.node.type == 'EMISSION':
        next_socket = NodeSocket(prev.node.inputs[0], prev.group_path)

    return {'next_socket': next_socket}


def gather_base_color_factor(info, export_settings):
    rgb, alpha = None, None

    if 'rgb_socket' in info:
        rgb = get_factor_from_socket(info['rgb_socket'], kind='RGB')
    if 'alpha_socket' in info:
        alpha = get_factor_from_socket(info['alpha_socket'], kind='VALUE')

    if rgb is None: rgb = [1.0, 1.0, 1.0]
    if alpha is None: alpha = 1.0

    rgba = [*rgb, alpha]
    if rgba == [1, 1, 1, 1]: return None
    return rgba


def gather_base_color_texture(info, export_settings):
    sockets = (info.get('rgb_socket', NodeSocket(None, None)), info.get('alpha_socket', NodeSocket(None, None)))
    sockets = tuple(s for s in sockets if s.socket is not None)
    if sockets:
        # NOTE: separate RGB and Alpha textures will not get combined
        # because gather_image determines how to pack images based on the
        # names of sockets, and the names are hard-coded to a Principled
        # style graph.
        unlit_texture, uvmap_info, _  = gltf2_blender_gather_texture_info.gather_texture_info(
            sockets[0],
            sockets,
            (),
            export_settings,
        )

        return unlit_texture, {'baseColorTexture': uvmap_info}
    return None, {}
