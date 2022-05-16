import configparser
config = configparser.ConfigParser()
if not config.read('config.ini'):
    print('Config file not found. Start by copying config.ini.example to config.ini and editing it.')
    exit(1)

# Remove quotes from config
for section in config.sections():
    for option in config.options(section):
        if "[" not in config[section][option] and "{" not in config[section][option]:
            config[section][option] = config[section][option].replace('"', '')
            config[section][option] = config[section][option].replace("'", '')
