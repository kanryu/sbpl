# SBPL
SBPL module for remote printing

## Summary
This provides the function of remote printing directly 
to the printer existing on your LAN by using SBPL 
(SATO Barcode Printer Language) provided by SATO Corp.

This enables arbitrary label cutting which can not be controlled
by a normal Windows printer.

This module has a function to print TrueType fonts using Freetype. Execute method ttf_write().

This module is a prototype and may not satisfy your work, 
but since it is Pure Python, you can add and change features yourself.


## Install

```shell
$ pip install sbpl
```

## Usage
```Python
comm = SG412R_Status5()
with comm.open("192.168.0.251", 1024):
    comm.prepare()

    # generate label...
    gen = LabelGenerator()
    with gen.packet_for_with():
        with gen.page_for_with():
            gen.set_label_size((1000, 3000))
            gen.rotate_270()
            gen.pos((260, 930))
            gen.codebar(("0004693003005000", 3, 100))
            gen.pos((160, 1000))
            gen.expansion((1,1))
            gen.bold_text("0004693003005000")
            gen.print()
    
    comm.send(gen.to_bytes())
    comm.finish()
```

You can describe print contents in JSON format and can specify them all together.

JSON:

```JSON
[
    {"host":"192.168.0.251", "port": 1024, "communication": "SG412R_Status5"},
    [
        {"set_label_size": [1000, 3000]},
        {"shift_jis": 0},
        {"rotate_270": 0},
        {"comment":"==ticket main=="},
        {"pos": [710, 130], "expansion": [6000], "ttf_write": "TEST CONSERT", "font": "mplus-1p-medium.ttf"},
        {"pos": [530, 1040], "expansion": [2700], "ttf_write": "Organizer: Python High School", "font": "mplus-1p-medium.ttf"},
        {"pos": [370, 50], "expansion": [3700], "ttf_write": "Friday, February 14, 2014 14:00", "font": "mplus-1p-medium.ttf"},
        {"pos": [300, 80], "expansion": [2800], "ttf_write": "Indoor playground", "font": "mplus-1p-medium.ttf"},
        {"pos": [230, 30], "expansion": [3500], "ttf_write": "Free seat $5.00", "font": "mplus-1p-medium.ttf"},
        {"pos": [180, 50], "expansion": [1800], "ttf_write": "Drinks can be brought in but alcohol is prohibited.", "font": "mplus-1p-medium.ttf"},
        {"comment":"==barcode=="},
        {"pos": [260, 930], "codebar": ["0004693003005000", 3, 100]},
        {"pos": [160, 1000], "expansion": [1,1], "bold_text": "0004693003005000"},
        {"comment":"==ticket parted=="},
        {"pos": [780, 1610], "expansion": [2500], "ttf_write": "TEST", "font": "mplus-1p-medium.ttf"},
        {"pos": [670, 1610], "expansion": [2500], "ttf_write": "CONSERT", "font": "mplus-1p-medium.ttf"},
        {"pos": [620, 1630], "expansion": [2000], "ttf_write": "Friday, February 14, 2014 14:00", "font": "mplus-1p-medium.ttf"},
        {"pos": [580, 1630], "expansion": [2000], "ttf_write": "14:00", "font": "mplus-1p-medium.ttf"},
        {"pos": [420, 1610], "expansion": [2000], "ttf_write": "Free seat", "font": "mplus-1p-medium.ttf"},
        {"pos": [330, 1600], "expansion": [2000], "ttf_write": "$5.00", "font": "mplus-1p-medium.ttf"},
        {"print": 1}
    ]
]
```

Python:

```Python
from sbpl import *

json_str = "(defined adobe)"
comm = SG412R_Status5()
gen = LabelGenerator()
parser = JsonParser(gen)
parser.parse(json_str)
parser.post(comm)
```

## License

MIT

## Author

Copyright 2018 KATO Kanryu(k.kanryu@gmail.com)
