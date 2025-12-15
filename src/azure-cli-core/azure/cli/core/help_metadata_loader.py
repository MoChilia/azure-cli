# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Fast help metadata loader that reads from per-module pre-generated JSON files instead of loading command table.
This significantly improves help performance for all commands.
"""

import json
import os
from knack.log import get_logger

logger = get_logger(__name__)

# Cache for loaded metadata: {module_name: metadata_dict}
_MODULE_METADATA_CACHE = {}

# Core metadata for root help (builtin commands like configure, find, etc.)
_CORE_METADATA_FILE = os.path.join(os.path.dirname(__file__), '_help_metadata.json')

# Cache for command_modules directory path
_COMMAND_MODULES_DIR = None


def _get_command_modules_dir():
    """Get the path to the command_modules directory."""
    global _COMMAND_MODULES_DIR
    if _COMMAND_MODULES_DIR is not None:
        return _COMMAND_MODULES_DIR
    
    # __file__ is in: src/azure-cli-core/azure/cli/core/help_metadata_loader.py
    # We need: src/azure-cli/azure/cli/command_modules/
    cli_path = os.path.dirname(os.path.dirname(__file__))  # azure/cli
    azure_path = os.path.dirname(cli_path)  # azure
    package_path = os.path.dirname(azure_path)  # src/azure-cli-core
    src_path = os.path.dirname(package_path)  # src
    _COMMAND_MODULES_DIR = os.path.join(src_path, 'azure-cli', 'azure', 'cli', 'command_modules')
    return _COMMAND_MODULES_DIR


def _get_module_metadata_path(module_name):
    """Get the metadata file path for a command module."""
    return os.path.join(_get_command_modules_dir(), module_name, '_help_metadata.json')


def _discover_all_modules():
    """Discover all available command modules by scanning the command_modules directory."""
    modules_dir = _get_command_modules_dir()
    if not os.path.exists(modules_dir):
        logger.debug("Command modules directory not found: %s", modules_dir)
        return []
    
    modules = []
    try:
        for entry in os.listdir(modules_dir):
            module_path = os.path.join(modules_dir, entry)
            # Check if it's a directory and has _help_metadata.json
            if os.path.isdir(module_path):
                metadata_file = os.path.join(module_path, '_help_metadata.json')
                if os.path.exists(metadata_file):
                    modules.append(entry)
    except Exception as e:
        logger.warning("Failed to discover modules: %s", e)
    
    return modules


def load_all_modules_metadata():
    """
    Load and aggregate metadata from all available modules for root help display.
    
    Returns:
        dict: Aggregated metadata with 'groups' and 'commands' keys from all modules.
    """
    aggregated = {
        'version': None,
        'groups': {},
        'commands': {}
    }
    
    # Load core metadata first
    core_metadata = load_module_metadata(None)
    if core_metadata:
        aggregated['version'] = core_metadata.get('version')
        aggregated['groups'].update(core_metadata.get('groups', {}))
        aggregated['commands'].update(core_metadata.get('commands', {}))
    
    # Discover and load all module metadata
    modules = _discover_all_modules()
    logger.debug("Discovered %d modules with metadata", len(modules))
    
    for module_name in modules:
        module_metadata = load_module_metadata(module_name)
        if module_metadata:
            aggregated['groups'].update(module_metadata.get('groups', {}))
            aggregated['commands'].update(module_metadata.get('commands', {}))
    
    logger.debug("Aggregated metadata: %d groups, %d commands", 
                 len(aggregated['groups']), len(aggregated['commands']))
    return aggregated


def _normalize_metadata_structure(raw_metadata):
    """
    Normalize metadata from array format to dictionary format.
    Supports both old dict format and new array format with rich details.
    Flattens nested groups/commands into dot notation for easy lookup.
    
    Args:
        raw_metadata: Raw metadata that may have 'groups' and 'commands' as arrays or dicts
    
    Returns:
        dict: Normalized metadata with 'groups' and 'commands' as dictionaries
    """
    normalized = {
        'version': raw_metadata.get('version'),
        'groups': {},
        'commands': {}
    }
    
    module_name = raw_metadata.get('name', '')
    
    def process_group(group, parent_path=''):
        """Recursively process a group and its nested groups/commands."""
        group_name = group.get('name')
        if not group_name:
            return
            
        # Build full path for this group
        full_path = f"{parent_path} {group_name}".strip() if parent_path else group_name
        if module_name and not full_path.startswith(module_name):
            full_path = f"{module_name} {full_path}"
        
        # Store group info
        normalized['groups'][full_path] = {
            'name': full_path,
            'summary': group.get('help', ''),
            'commands': group.get('commands', []),
            'groups': group.get('groups', [])
        }
        
        # Process nested commands in this group
        for cmd in group.get('commands', []):
            cmd_name = cmd.get('name')
            if cmd_name:
                cmd_full_path = f"{full_path} {cmd_name}"
                normalized['commands'][cmd_full_path] = {
                    'name': cmd_full_path,
                    'summary': cmd.get('help', ''),
                    'examples': cmd.get('examples', []),
                    'parameters': cmd.get('parameters', [])
                }
        
        # Process nested subgroups
        for subgroup in group.get('groups', []):
            process_group(subgroup, full_path)
    
    # Handle groups
    groups_data = raw_metadata.get('groups', {})
    if isinstance(groups_data, list):
        # Array format - convert to dict, preserving all details
        for group in groups_data:
            process_group(group)
    elif isinstance(groups_data, dict):
        # Already in dict format
        normalized['groups'] = groups_data
    
    # Handle top-level commands
    commands_data = raw_metadata.get('commands', {})
    if isinstance(commands_data, list):
        # Array format - convert to dict, preserving all details
        for cmd in commands_data:
            cmd_name = cmd.get('name')
            if cmd_name:
                full_cmd_name = f"{module_name} {cmd_name}" if module_name else cmd_name
                normalized['commands'][full_cmd_name] = {
                    'name': full_cmd_name,
                    'summary': cmd.get('help', ''),
                    'examples': cmd.get('examples', []),
                    'parameters': cmd.get('parameters', [])
                }
    elif isinstance(commands_data, dict):
        # Already in dict format
        normalized['commands'] = commands_data
    
    return normalized


def load_module_metadata(module_name=None):
    """
    Load help metadata for a specific module.
    
    Args:
        module_name: Name of the module (e.g., 'vm', 'network'). If None, loads core metadata.
    
    Returns:
        dict: Metadata with 'groups' and 'commands' keys, or None if not found.
    """
    if module_name is None:
        module_name = '_core'
        metadata_file = _CORE_METADATA_FILE
    else:
        if module_name in _MODULE_METADATA_CACHE:
            return _MODULE_METADATA_CACHE[module_name]
        metadata_file = _get_module_metadata_path(module_name)
    
    try:
        if not os.path.exists(metadata_file):
            logger.debug("Help metadata file not found for module '%s': %s", module_name, metadata_file)
            return None
        
        with open(metadata_file, 'r', encoding='utf-8') as f:
            raw_metadata = json.load(f)
        
        # Normalize the structure (handles both array and dict formats)
        metadata = _normalize_metadata_structure(raw_metadata)
        
        _MODULE_METADATA_CACHE[module_name] = metadata
        logger.debug("Loaded help metadata for module '%s' with %d groups and %d commands",
                     module_name,
                     len(metadata.get('groups', {})),
                     len(metadata.get('commands', {})))
        return metadata
    except Exception as e:
        logger.warning("Failed to load help metadata for module '%s': %s", module_name, e)
        return None


def get_module_index():
    """
    Load the module index that maps top-level groups to their modules.
    This is the existing commandIndex.json.
    """
    try:
        index_file = os.path.join(os.path.dirname(__file__), 'commandIndex.json')
        if not os.path.exists(index_file):
            return None
        
        with open(index_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load command index: %s", e)
        return None


def find_module_for_command(command_parts):
    """
    Find which module handles a command based on commandIndex.json or by checking metadata files.
    
    Args:
        command_parts: List of command parts (e.g., ['vm', 'list'] or ['network', 'vnet', 'create'])
    
    Returns:
        str: Module name (e.g., 'vm', 'network') or None if not found.
    """
    if not command_parts:
        return None
    
    # First try using commandIndex if available
    index = get_module_index()
    if index:
        # Try to find the command in the index
        # Look for exact match or longest prefix match
        for length in range(len(command_parts), 0, -1):
            prefix = ' '.join(command_parts[:length])
            if prefix in index:
                module_info = index[prefix]
                # Extract module name from the path
                # Format: "azure.cli.command_modules.vm#"
                if isinstance(module_info, str) and '#' in module_info:
                    module_path = module_info.split('#')[0]
                    if 'command_modules.' in module_path:
                        module_name = module_path.split('command_modules.')[1]
                        return module_name
    
    # Fallback: assume the first part is the module name and check if its metadata exists
    # This is a reasonable heuristic since most commands follow the pattern: az <module> <subcommand>
    if command_parts:
        module_name = command_parts[0]
        metadata_path = _get_module_metadata_path(module_name)
        if os.path.exists(metadata_path):
            return module_name
    
    return None


def load_metadata_for_command(command_parts):
    """
    Load metadata for a command by finding its module and loading that module's metadata.
    For root help (empty command_parts), aggregates metadata from all modules.
    
    Args:
        command_parts: List of command parts (e.g., ['vm'] or ['network', 'vnet'])
    
    Returns:
        dict: Metadata dict or None if not found.
    """
    if not command_parts:
        # Root help - aggregate metadata from all modules
        return load_all_modules_metadata()
    
    module_name = find_module_for_command(command_parts)
    if not module_name:
        # No module found
        return None
    
    return load_module_metadata(module_name)


def get_command_metadata(command_parts, is_group=False):
    """
    Get metadata for a specific command or group.
    
    Args:
        command_parts: List of command parts (e.g., ['vm', 'list'])
        is_group: True if this is a group, False if it's a command
    
    Returns:
        dict: Metadata with 'name' and 'summary' keys, or None if not found.
    """
    metadata = load_metadata_for_command(command_parts)
    if not metadata:
        return None
    
    command_str = ' '.join(command_parts)
    collection = metadata.get('groups' if is_group else 'commands', {})
    return collection.get(command_str)


def has_metadata_for_command(command_parts):
    """Check if metadata exists for a command."""
    module_name = find_module_for_command(command_parts)
    if module_name:
        metadata_file = _get_module_metadata_path(module_name)
        return os.path.exists(metadata_file)
    # Check core metadata
    return os.path.exists(_CORE_METADATA_FILE)
