#!/usr/bin/env python

# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Generate per-module help metadata JSON files from command table.
This should be run during build time to create static help metadata files for each module.

Usage:
    python scripts/generate_help_metadata.py
    
This will generate:
    - src/azure-cli-core/azure/cli/core/_help_metadata.json (for builtin commands)
    - src/azure-cli/azure/cli/command_modules/{module}/_help_metadata.json (for each module)
"""

import json
import sys
import os
import argparse
from collections import defaultdict


def _get_module_from_loader(loader_name):
    """Extract module name from loader class name."""
    # Loader format: azure.cli.command_modules.vm#VmCommandsLoader
    if '#' in loader_name:
        module_path = loader_name.split('#')[0]
        if 'command_modules.' in module_path:
            return module_path.split('command_modules.')[1]
    return None


def _get_command_module(command_name, command_index):
    """Determine which module a command belongs to using commandIndex."""
    # Try exact match first
    if command_name in command_index:
        loader = command_index[command_name]
        return _get_module_from_loader(loader)
    
    # Try prefix match (for subcommands)
    parts = command_name.split()
    for i in range(len(parts), 0, -1):
        prefix = ' '.join(parts[:i])
        if prefix in command_index:
            loader = command_index[prefix]
            return _get_module_from_loader(loader)
    
    return '_core'  # Builtin/core commands


def generate_help_metadata():
    """Generate per-module help metadata from command table."""
    # Setup CLI
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    
    sys.path.insert(0, os.path.join(repo_root, 'src', 'azure-cli'))
    sys.path.insert(0, os.path.join(repo_root, 'src', 'azure-cli-core'))
    sys.path.insert(0, os.path.join(repo_root, 'src', 'azure-cli-telemetry'))

    from azure.cli.core import get_default_cli
    from azure.cli.core.file_util import create_invoker_and_load_cmds_and_args
    
    print("Initializing Azure CLI...")
    cli = get_default_cli()
    
    print("Loading command table and help...")
    create_invoker_and_load_cmds_and_args(cli)
    
    command_loader = cli.invocation.commands_loader
    command_table = command_loader.command_table
    command_group_table = command_loader.command_group_table
    
    print(f"Found {len(command_table)} commands and {len(command_group_table)} groups")
    
    # Load command index to determine module ownership
    index_file = os.path.join(repo_root, 'src', 'azure-cli-core', 'azure', 'cli', 'core', 'commandIndex.json')
    with open(index_file, 'r', encoding='utf-8') as f:
        command_index = json.load(f)
    
    # Organize metadata by module
    module_metadata = defaultdict(lambda: {
        'version': cli.get_cli_version(),
        'groups': {},
        'commands': {}
    })
    
    # Extract command groups
    for group_name in sorted(command_group_table.keys()):
        module_name = _get_command_module(group_name, command_index)
        
        try:
            # Get group help
            from azure.cli.core._help import CliGroupHelpFile
            parser = cli.invocation.parser
            help_file = CliGroupHelpFile(cli.invocation.help, group_name, parser)
            
            module_metadata[module_name]['groups'][group_name] = {
                'name': group_name,
                'summary': getattr(help_file, 'short_summary', '') or ''
            }
        except Exception as e:
            print(f"Warning: Could not extract help for group '{group_name}': {e}")
            module_metadata[module_name]['groups'][group_name] = {
                'name': group_name,
                'summary': ''
            }
    
    # Extract commands
    for cmd_name, cmd in sorted(command_table.items()):
        module_name = _get_command_module(cmd_name, command_index)
        
        try:
            module_metadata[module_name]['commands'][cmd_name] = {
                'name': cmd_name,
                'summary': getattr(cmd, 'short_summary', '') or getattr(cmd, 'description', '') or ''
            }
        except Exception as e:
            print(f"Warning: Could not extract metadata for command '{cmd_name}': {e}")
            module_metadata[module_name]['commands'][cmd_name] = {
                'name': cmd_name,
                'summary': ''
            }
    
    return dict(module_metadata), repo_root


def main():
    parser = argparse.ArgumentParser(description='Generate per-module help metadata JSON files')
    parser.add_argument('--modules', nargs='*', help='Specific modules to generate (default: all)')
    args = parser.parse_args()
    
    print("=" * 80)
    print("Generating Azure CLI Per-Module Help Metadata")
    print("=" * 80)
    
    module_metadata, repo_root = generate_help_metadata()
    
    total_groups = 0
    total_commands = 0
    files_written = 0
    
    for module_name, metadata in sorted(module_metadata.items()):
        # Skip if specific modules requested and this isn't one
        if args.modules and module_name not in args.modules and module_name != '_core':
            continue
        
        # Determine output path
        if module_name == '_core':
            output_path = os.path.join(repo_root, 'src', 'azure-cli-core', 'azure', 'cli', 'core', '_help_metadata.json')
        else:
            output_path = os.path.join(repo_root, 'src', 'azure-cli', 'azure', 'cli', 'command_modules', 
                                       module_name, '_help_metadata.json')
        
        # Skip if directory doesn't exist (module might not be in this repo)
        if not os.path.exists(os.path.dirname(output_path)):
            print(f"Skipping {module_name}: directory not found")
            continue
        
        # Write metadata file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        file_size = os.path.getsize(output_path) / 1024
        num_groups = len(metadata['groups'])
        num_commands = len(metadata['commands'])
        
        print(f"✓ {module_name:20s} {file_size:6.1f} KB  ({num_groups:4d} groups, {num_commands:4d} commands)")
        
        total_groups += num_groups
        total_commands += num_commands
        files_written += 1
    
    print("=" * 80)
    print(f"Done! Generated {files_written} metadata files")
    print(f"  - {total_groups} command groups")
    print(f"  - {total_commands} commands")
    print("\nMetadata files are stored alongside their respective modules:")
    print("  - Core: src/azure-cli-core/azure/cli/core/_help_metadata.json")
    print("  - Modules: src/azure-cli/azure/cli/command_modules/{module}/_help_metadata.json")


if __name__ == '__main__':
    main()
