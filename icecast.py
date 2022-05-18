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


import xml.etree.ElementTree as ET

# Open original file
et = xml.etree.ElementTree.parse('file.xml')

# Append new tag: <a x='1' y='abc'>body text</a>
new_tag = xml.etree.ElementTree.SubElement(et.getroot(), 'a')
new_tag.text = 'body text'
new_tag.attrib['x'] = '1' # must be str; cannot be an int
new_tag.attrib['y'] = 'abc'

# Write back to file
#et.write('file.xml')
# et.write('file_new.xml')
