################################################################################
#      ____  ___    ____  ________     ____  ____  ______
#     / __ \/   |  / __ \/  _/ __ \   / __ )/ __ \/_  __/
#    / /_/ / /| | / / / // // / / /  / __  / / / / / /
#   / _, _/ ___ |/ /_/ // // /_/ /  / /_/ / /_/ / / /
#  /_/ |_/_/  |_/_____/___/\____/  /_____/\____/ /_/
#
#
# Matheus Fillipe 18/05/2022
# MIT License
################################################################################


import configparser
import json

parsed_config = configparser.ConfigParser()
if not parsed_config.read('config.ini'):
    print('Config file not found. Start by copying config.ini.example to config.ini and editing it.')
    exit(1)

config = dict()
for section in parsed_config.sections():
    config[section] = dict()
    for option in parsed_config.options(section):
        upper_option = option.upper()
        config[section][upper_option] = parsed_config[section][option] = parsed_config[section][option].strip()
        # Remove quotes from strings
        if parsed_config[section][option].startswith('"') and parsed_config[section][option].endswith('"') or\
                parsed_config[section][option].startswith("'") and parsed_config[section][option].endswith("'"):
            config[section][upper_option] = parsed_config[section][option][1:-1]
        # Parse lists
        elif "[" in parsed_config[section][option] or "{" in parsed_config[section][option]:
            config[section][upper_option] = json.loads(
                parsed_config[section][option])
        # Parse ints
        elif parsed_config[section][option].isdigit():
            config[section][upper_option] = int(parsed_config[section][option])
        # Parse floats
        elif parsed_config[section][option].replace('.', '', 1).isdigit():
            config[section][upper_option] = float(
                parsed_config[section][option])
