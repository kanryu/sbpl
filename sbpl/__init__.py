# -*- coding: utf-8 -*-
"""
SBPL module for remote printing

This provides the function of remote printing directly 
to the printer existing on your LAN by using SBPL 
(SATO Barcode Printer Language) provided by SATO Corp.

This enables arbitrary label cutting which can not be controlled
by a normal Windows printer.

This module is a prototype and may not satisfy your work, 
but since it is Pure Python, you can add and change features yourself.
"""
import json
import socket

STX = "\x02"
ESC = "\x1b"
ETX = "\x03"

# SBPL PROGRAMMING REFERENCE For printer model: GL408e / GL412e
# TABLE 26: CODE128 DATA VALUES (<ESC>BG)
# VALUE | SUBSET A | SUBSET B | SUBSET C
# 102   | FNC1 >F  | FNC1 >F  | FNC1 >F
# 103   | SUBSET A START CODE >G
# 104   | SUBSET B START CODE .H
# 105   | SUBSET C START CODE >I
CODE128_FNC1 = "\x66"
CODE128_START_CODE_A = "\x67"
CODE128_START_CODE_B = "\x68"
CODE128_START_CODE_C = "\x69"

B_STX = b"\x02"
B_ESC = b"\x1b"
B_ETX = b"\x03"
B_CODE128_FNC1 = b"\x67"
B_CODE128_START_CODE_A = b"\x67"
B_CODE128_START_CODE_B = b"\x68"
B_CODE128_START_CODE_C = b"\x69"

class TtfGlyph:
    """
    Handle glyph data for one character of TrueType font.

    Fonts are rendered by FreeType-py and kept by instances of this class.
    Each glyph is rendered as a 1 bpp monochrome bitmap and issued as a GB command.
    It can be cached in units of character strings and SBPL can be actually 
    generated after calculating the range of output character strings.

    :param c: The character to render. len(c)==1
    :type c: str
    :param face: freetype.face
    :type face: freetype.face
    :param expansion: Font expansion. maybe expansion = XXpt*72
    :type expansion: int
    """
    _c = ''
    _buffer = []
    _bitmap_top = 0
    _bitmap_left = 0
    _width = 0
    _rows = 0
    _stride = 0
    _pwidth = 0
    _pheight = 0
    _bwidth = 0
    _bheight = 0
    _expansion = 0
    
    def __init__(self, c, face, expansion):
        self._c = c
        self._expansion = expansion
        if c == ' ' or c == '¥t': # 半角スペース
            self._width = expansion // (72*2)
            return
        if c == '　': # 全角スペース
            self._width = expansion // 72
            return

        import freetype

        flags = freetype.FT_LOAD_FLAGS['FT_LOAD_RENDER'] | freetype.FT_LOAD_FLAGS['FT_LOAD_MONOCHROME'] | freetype.FT_LOAD_TARGETS['FT_LOAD_TARGET_MONO']
        #print("c:", c)
        face.load_char(c, flags)
        glyph = face.glyph
        bitmap = glyph.bitmap
        self._buffer = bitmap.buffer
#        self._horiAdvance = glyph.metrics.horiAdvance
        self._bitmap_top = glyph.bitmap_top       # offset to the top of the glyph bitmap
        self._bitmap_left = glyph.bitmap_left

        self._width = bitmap.width                # logical width of the glyph bitmap
        self._rows = bitmap.rows                  # height of the glyph bitmap
        self._stride = len(self._buffer) // self._rows # byte length of each line
        
        self._pwidth = (self._width+(64-1))//64*64 # output width (packed by 8px, e.g. 63 -> 64, 65 -> 128)
        self._pheight = (self._rows+(64-1))//64*64 # output height(packed by 8px, e.g. 63 -> 64, 65 -> 128)
        if self._pwidth < self._pheight: self._pwidth = self._pheight
        if self._pwidth > self._pheight: self._pheight = self._pwidth
        
        self._bwidth = self._pwidth // 8
        self._bheight = self._pheight // 8
        
#        print("char: ", c, x, y)
#        print('bitmap:', bitmap.width, self._rows, self._stride, len(bitmap.buffer), self._width)
#        print('pwidth, pheight:', self._pwidth, self._pheight, self._bwidth, self._bheight)
#        print('metrics.horiAdvance:', self._horiAdvance)
    
    def offset_x(self):
        """Returns the offset to the next character"""
        return self._width+(self._bitmap_left*2)

    def offset(self):
        """Return a tuple of the offset to the next character"""
        return (self._offset_x(), 0)

    def offset_top(self):
        """Vertical offset of character glyph"""
        return self._bitmap_top_

    def to_bytes(self):
        """
        Returns a raw bitmap of 1bpp specified by (pwidth, pheight)

        The bitmap requested by the 'GB' command is a monochrome 1bpp, 
        it must be a unit of 8×8, and the number of pixels in the vertical 
        and horizontal directions must be the same.

        :rtype: bytearray
        """
        bits = bytearray()
        for r in range(self._pheight): 
            # 下端は0ベタで埋める
            if r >= self._rows:
                bits = bits + bytes(self._bwidth)
                continue
            # まずグリフデータを左端から書き出す
            bits = bits + bytes(bytearray(self._buffer[r*self._stride:(r+1)*self._stride]))
            if self._stride < self._bwidth: # 足りない場合は0ベタで埋める
                bits = bits + bytes(self._bwidth - self._stride)
        return bits

    def generate(self, gen, position):
        """
        Print the stored glyph data

        :param gen: Generator
        :type gen: LabelGenerator
        :param position: Coordinates to be printed
        :type position: tuple or list of 2-int
        """
        gen.pos(gen.glyph_offset(position, (self._bitmap_left, self._bitmap_top)))

        pt = 'GB{0:03d}{1:03d}'.format(self._bheight, self._bwidth)
        gen.extend_str((ESC, pt))
        gen.packets += self._to_bytes()

class LabelGenerator:
    """
    Generate a byte stream to be printed by SBPL.

    Various commands for printing are held as methods, and by executing them, a byte string of SBPL is generated and held.

    :param packets: (optional) Cached bytearray will be the printing packet
    :type packets: bytearray
    """
    _packets = bytearray()
    _encoding = 'cp932' # マイクロソフト拡張のShift_JIS
    _face = None
    _font = "mplus-1p-black.ttf"
    _last_expansion = 30
    _pitch = 0
    _rotate = 0
    _bar_ratio = 'B' # for ratio 1:3
    _getfontpath = None
    
    _ratio_map = {
        '1:3': 'B', # NW-7/CODE39/itf/JAN-13/JAN-8/Code 2 of 5/Matrix 2 of 5/MSI/CODE93/UPC-E/BOOKLAND/CODE128/UPC-A/EAN128/POSTNET
        '1:2': 'D', # NW-7/CODE39/itf/JAN-13/JAN-8/Code 2 of 5/Matrix 2 of 5/UPC-A
        '2:5': 'BD' # NW-7/CODE39/itf/JAN-13/JAN-8/Code 2 of 5/Matrix 2 of 5/UPC-A
    }

    def __init__(self,packets=bytearray()):
        self._packets = packets

    def extend_str(self, tp):
        """
        a list of arbitrary character strings into a string and then encode() and add into the bytearray
        """
        self._packets += ''.join(tp).encode(self._encoding)

    def to_bytes(self):
        """
        bytearray to bytes
        """
        return bytes(self._packets)

    def begin_packet(self):
        """
        A packet must first execute this method at the beginning.
        
        You must execute end_packet() later.
        To print multiple pages, execute the necessary number of begin_packet()/end_packet()
        """
        self._packets += B_STX
        return self

    def end_packet(self):
        """
        A packet must last execute this method at the ending.
        
        You must execute begin_packet() first.
        To print multiple pages, execute the necessary number of begin_packet()/end_packet()
        """
        self._packets += B_ETX
        return self

    def packet_for_with(self):
        """
        with gen.packet_for_with():
            gen.somemethod() # generate inner packets
        """
        class PacketGather:
            generator = None
            def __init__(self, g):
                self._generator = g
            def __enter__(self):
                self._generator.begin_packet()
                return self
            def __exit__(self, ex_type, ex_value, trace):
                self._generator.end_packet()
        return PacketGather(self)

    def begin_page(self):
        """
        Each page must first execute this command at the beginning.
        
        You must execute begin_packet() just before.
        You must execute end_page() later.
        To print multiple pages, execute the necessary number of begin_page()/end_page()
        """
        self.extend_str((ESC, 'A'))
        return self

    def end_page(self):
        """
        Each page must last execute this command at the ending.
        
        You must execute begin_page() first.
        You must execute end_packet() immediately after that.
        To print multiple pages, execute the necessary number of begin_page()/end_page()
        """
        self.extend_str((ESC, 'Z'))
        return self

    def page_for_with(self):
        """
        with gen.page_for_with():
            gen.somemethod() # generate inner the page
        """
        class PageGather:
            _generator = None
            def __init__(self, g):
                self._generator = g
            def __enter__(self):
                self._generator.begin_page()
                return self
            def __exit__(self, ex_type, ex_value, trace):
                self._generator.end_page()
        return PageGather(self)
    
    def set_label_size(self, size):
        """
        Specify the size of the label to be printed.
        
        :param size: Specify the size of the label in two-dimensional(width,height) pixel coordinates. e.g. (100, 200)
        """
        sz = 'A1V{0[1]:04d}H{0[0]:04d}'.format(size)
        self.extend_str((ESC, sz))
        return self
        
    def shift_jis(self):
        """
        Shift_JIS is specified as the character code to be sent to the printer.

        It must be executed when printing multi-byte character strings.
        However, the string given to each method must be as str (automatically encode() is executed)
        """
        self.extend_str((ESC, 'KC1'))
        return self

    def skip_cutting(self):
        """
        Designate the printer not to cut the current label.

        The behavior of this command varies depending on the settings 
        of the printer itself. Use it with setting to cut every page.
        This command is valid only on the label that was executed, 
        and it needs to be executed again on the next page.
        """
        self.extend_str((ESC, 'CT0'))
        return self
        
    def print(self, num=1):
        """
        How many copies of the current label should be printed.
        
        If this command is not executed, labels are not printed.
        """
        nm = 'Q{0}'.format(num)
        self.extend_str((ESC, nm))

    def rotate_0(self):
        """
        Set rotation of coordinate axis to 0 degree

        This is the default orientation of SATO's printer, 
        and when you look at the label printed standing behind the printer, 
        it is the direction in which the string is printed just as you have seen.
        """
        self.extend_str((ESC, '%0'))
        self._rotate = 0

    def rotate_90(self):
        """
        Set rotation of coordinate axis to 90 degree
        """
        self.extend_str((ESC, '%1'))
        self._rotate = 90

    def rotate_180(self):
        """
        Set rotation of coordinate axis to 180 degree
        """
        self.extend_str((ESC, '%2'))
        self._rotate = 180

    def rotate_270(self):
        """
        Set rotation of coordinate axis to 0 degree

        When you see the label printed on the right side of the printer, 
        it is the orientation in which the string is printed exactly as you saw. 
        You will execute this command if you want to use the paper sideways.
        """
        self.extend_str((ESC, '%3'))
        self._rotate = 270

    def pos(self, position):
        """
        The start coordinates of the printing command to be continued are made.
        
        Note that when you see a label standing behind the printer and its printed label, 
        its upper left coordinate is (0, 0). x is rightward and y is downward. 
        This instruction does not change with the rotate instruction.
        
        :param position: Two-dimensional coordinates representing the position(x,y) e.g. (100, 200)
        """
        self.extend_str((ESC, 'V{0[1]:04d}'.format(position), ESC, 'H{0[0]:04d}'.format(position)))
        return self

    def line(self, length, thickness):
        """
        Pull a vertical or horizontal lines (diagonal lines can not be pulled)
        
        :param length: Specify only one of x or y in two-dimensional coordinates e.g. (123, 0) or (0, 456)
        :param thickness: Line thickness (1-99)
        """
        if not length or len(length) < 2 or (length[0] == 0 and length[1] == 0): raise NotImplementedError()
        if length[0] != 0 and length[1] != 0: raise NotImplementedError()
        b = 'H' if length[0] != 0 else 'V'
        ln = length[0] if length[0] != 0 else length[1]
        pt = 'FW{0:02d}{1}{2:04d}'.format(thickness, b, ln)
        self.extend_str((ESC, pt))

    def rectangle(self, size, thickness):
        """
        Draw a rectangle
        
        :param size: (width,height) e.g. (123, 456)
        :param thickness: Line thickness e.g.(2,2)
        """
        #print(size, thickness)
        pt = 'FW{0[0]:02d}{0[1]:02d}V{1[1]:04d}H{1[0]:04d}'.format(thickness, size)
        self.extend_str((ESC, pt))

    def expansion(self, exp=(1,1), pitch=0):
        """
        Specify magnification and pitch of character printing following this command
        
        :param exp: Two-dimensional coordinates representing magnification (H_expansion,y_expansion) e.g. (1,2)
        :param pitch: Specify the pitch between characters in pixels (0-99)
        """
        ex = 'L{0[0]:02d}{0[1]:02d}'.format(exp)
        pt = 'P{0:02d}'.format(pitch)
        self.extend_str((ESC, pt, ESC, ex))
        return self
    
    def write_text(self, text):
        """
        Print specified character string with built-in font
        
        :param text: String to output. For multibyte characters, it must be a character that exists in CP932
        :type text: str
        """
        self.extend_str((ESC, 'K9B', text))
        return self

    def bold_text(self, text):
        """
        Print specified character string with built-in bold font
        
        :param text: String to output. Only alphanumeric symbols are valid
        """
        self.extend_str((ESC, 'X22,', text))
        return self

    def barcode_ratio(self, ratio='1:3'):
        """
        Change the size of the barcode by changing the space between the bars.
        
        However, there is a barcode that can not be output if it is set to other than '1:3'.
        """
        self._bar_ratio = self._ratio_map['1:3']
        if ratio in self._ratio_map:
            self._bar_ratio = self._ratio_map[ratio]

    def code_39(self, text, pitch, height):
        """
        Output barcode of CODE 39 standard

        Valid characters: numbers, alphabets, symbols（-,.,(space),＊,$,／,+,%）の43 charactors
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print. Automatically enclosed in '*'
        """
        pt = self._bar_ratio + '1{0:02d}{1:03d}'.format(pitch, height)
        if text[0] != "*": text = '*' + text + '*'
        self.extend_str((ESC, pt, text))
        return self

    def code_93(self, text, pitch, height):
        """
        Output barcode of CODE 93 standard

        Valid characters: numbers, alphabets, symbols.（-,.,(space),＊,$,／,+,%） Four types of shift characters
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print.
        """
        pt = 'BC{0:02d}{1:03d}{2:02d}'.format(pitch, height, len(text))
        self.extend_str((ESC, pt, text))
        return self

    def code_128(self, text, pitch, height, code='B'):
        """
        Output barcode of CODE 128 standard

        Valid characters: numbers, alphabets, symbols.（-,.,(space),＊,$,／,+,%） Four types of shift characters
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print.
        :param code: Specify code start allowed by Code 128. A, B, C are valid, default is B. See the standard for details.
        """
        pt = self._bar_ratio + 'G{0:02d}{1:03d}'.format(pitch, height)
        if code == "C":
            self.extend_str((ESC, pt, '>I>F', text))
            return self
        if code == "A":
            self.extend_str((ESC, pt, '>G>F', text))
            return self

        self.extend_str((ESC, pt, '>F', text))
        return self
        
    def jan_13(self, text, pitch, height):
        """
        Output barcode of JAN 13 standard

        Valid characters: numbers
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print. Must be 11 or 13 chars.
        """
        if len(text) < 11 or 13 < len(text)  : raise "JAN-13: valid range: 11-13"
        pt = self._bar_ratio + '3{0:02d}{1:03d}'.format(pitch, height)
        self.extend_str((ESC, pt, text))

    def jan_8(self, text, pitch, height):
        """
        Output barcode of JAN 8 standard

        Valid characters: numbers
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print. Must be 6 or 8 chars.
        """
        if len(text) < 6 or 8 < len(text)  : raise "JAN-8: valid range: 6-8"
        pt = self._bar_ratio + '4{0:02d}{1:03d}'.format(pitch, height)
        self.extend_str((ESC, pt, text))

    def codabar(self, text, pitch, height):
        """
        Output barcode of NW-7(CODABAR) standard

        Valid characters: numbers, A,B,C,D, symbols. (-,$,/, . ,+)
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print.
        """
        pt = self._bar_ratio + '0{0:02d}{1:03d}'.format(pitch, height)
        self.extend_str((ESC, pt, text))
        return self

    def itf2of5(self, text, pitch, height):
        """
        Output barcode of Interleaved 2 of 5 standard

        Valid characters: numbers
        
        :param pitch: Barcode thickness. When the number is increased, the width suddenly increases
        :param height: Bar length of the bars. Pixel unit(1-999)
        :param text: String to print.
        """
        pt = self._bar_ratio + '2{0:02d}{1:03d}'.format(pitch, height)
        self.extend_str((ESC, pt, text))
        return self

    def set_font_path(self, getfontpath):
        """
        Resolve the PATH of the font file.
        
        If a font file exists other than the current directory, 
        it is necessary to supplement this font path by calling this method beforehand. 
        Give a function.
        
        :param getfontpath: Specify a function that takes str as an argument and returns str
        """
        self._getfontpath = getfontpath
        return self

    def ttf_face(self, font, expansion, pitch):
        """
        Freetype.Face is acquired using Freetype-py.
        
        In the windows environment, dll is required under the name "freetype.dll" in the execution directory.
        """
        import freetype
        fontpath = self._getfontpath(font) if self._getfontpath else font
        if (not self._face) or self._font != fontpath:
            self._face = freetype.Face(fontpath)
            self._font = fontpath
        self._face.set_char_size(*expansion)
        self._last_expansion = expansion[0]
        self._pitch = pitch

    def ttf_write(self, text, pos, maxwidth, align):
        """
        Print with a GB instruction while rendering TrueType fonts

        As GB instruction can usually print only one character, this class realizes processing for each character
        
        :param text: The output character string. Line breaks are ignored. Halfwidth and double-byte spaces are treated as fixed width shifted respectively.
        :param pos: Start coordinate to be printed. The positional relationship between pos and character string changes by rotate.
        :param maxwidth: (optional)Specify the maximum width of the drawing area. The start position when center or right is specified with align is changed. Trimed when exceeding the maximum width.
        :param align: (optional)Change the left and right position of the character string. center is the center of maxwidth, right is the right end.
        """
        x, y = pos
        glyphs = []
        totalwidth = 0
        for t in text:
            if t == '\r' or t == '\n': # 改行コードは無視
                continue
            g = TtfGlyph(t, self._face, self._last_expansion)
            if maxwidth != None and totalwidth + g.offset_x() > maxwidth:
                break
            totalwidth += g.offset_x()
            glyphs.append(g)

        x, y = self.glyph_offset((x,y), (0, -(self._last_expansion // 72)))
        if align == 'center': x, y = self.glyph_offset((x,y), ((maxwidth - totalwidth)//2, 0))
        if align == 'right': x, y = self.glyph_offset((x,y), (maxwidth - totalwidth, 0))

        for g in glyphs:
            if g.buffer:
                g.generate(self, (x, y))
            x, y = self.glyph_offset((x+self._pitch,y), g.offset())

    def glyph_offset(self, pos, offset):
        """
        Coordinate offset calculation corresponding to rotate
        """
        x, y = pos
        if self._rotate == 0:
            x += offset[0]
            y -= offset[1]
        if self._rotate == 90:
            x -= offset[1]
            y -= offset[0]
        if self._rotate == 180:
            x -= offset[0]
            y += offset[1]
        if self._rotate == 270:
            x += offset[1]
            y += offset[0]
        return (x, y)

class JsonParser:
    """
    Provide functions that can specify printing by SBPL with JSON.
    
    Even a simple example of SBPL printing requires the execution of many commands. 
    It is difficult to specify printing contents over a plurality of pages by a program, 
    and correction becomes difficult. So we made it possible to designate all at once by JSON.
    
    - The outside of JSON is always a list, and the inside is an object or list.
    - Object specifies the host name of the print server to be printed, it can be specified only once at the beginning.
    - The list includes a print instruction for one page in one list in the list of print commands.

    for example::

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

    usage::

        json_str = "(defined adobe)"
        comm = SG412R_Status5()
        gen = LabelGenerator()
        parser = JsonParser(gen)
        parser.parse(json_str)
        parser.post(comm)


    :param generator: Instances of LabelGenerator or its derived classes
    """
    _gen = None
    _comm_setting = None
    def __init__(self, generator):
        self._gen = generator

    def parse(self, json_str):
        """
        Issue the SBPL command while reading the contents of JSON.
        
        :param json: JSON which describes contents to be printed. If a character string is given, it is passed to json.load()
        :type json: str, or return value of json.loads()
        """
        self._json = json_str
        if type(json_str) == str:
            self._json = json.loads(json_str, encoding='utf-8')
        for page in self._json:
            if type(page) == dict:
                self._comm_setting = page
                continue
            with self._gen.packet_for_with():
                with self._gen.page_for_with():
                    for line in page:
                        self.parse_line(line)

    def post(self, comm):
        """
        Execute remote printing using communication settings described in JSON
        
        When the print destination is fixed, it is not necessary to include it in JSON, 
        but it is required to select _comm_setting manually or not to call this method.
        
        :param comm: Communication module for SATO printer. For example, an instance of SG412R_Status5
        """
        with comm.open(self._comm_setting["host"], self._comm_setting["port"]):
            comm.prepare()
            # generate label...
            comm.send(self._gen.to_bytes())
            comm.finish()

    def parse_line(self, line):
        """
        Convert the instruction described in JSON to SBPL command
        
        :param line: The dict expressing the instruction described in JSON
        """
        if 'set_label_size' in line:
            self._gen.set_label_size(line['set_label_size'])
        if 'line' in line:
            self._gen.pos(line['pos'])
            self._gen.line(line['line'], line['thickness'])
        if 'rectangle' in line:
            self._gen.pos(line['pos'])
            self._gen.rectangle(line['rectangle'], line['thickness'])
        if 'write_text' in line:
            self._gen.pos(line['pos'])
            self._gen.expansion(line['expansion'], line.get('pitch', 0))
            self._gen.write_text(line['write_text'])
        if 'bold_text' in line:
            self._gen.pos(line['pos'])
            self._gen.expansion(line['expansion'], line.get('pitch', 0))
            self._gen.bold_text(line['bold_text'])
        if 'barcode_ratio' in line:
            self._gen.barcode_ratio(line['barcode_ratio'])
        if 'code_39' in line:
            self._gen.pos(line['pos'])
            self._gen.code_39(*line['code_39'])
        if 'code_93' in line:
            self._gen.pos(line['pos'])
            self._gen.code_93(*line['code_93'])
        if 'codabar' in line:
            self._gen.pos(line['pos'])
            self._gen.codabar(*line['codabar'])
        if 'code_128' in line:
            self._gen.pos(line['pos'])
            self._gen.code_128(*line['code_128'])
        if 'jan_13' in line:
            self._gen.pos(line['pos'])
            self._gen.jan_13(*line['jan_13'])
        if 'itf2of5' in line:
            self._gen.pos(line['pos'])
            self._gen.itf2of5(*line['itf2of5'])
        if 'skip_cutting' in line:
            self._gen.skip_cutting()
        if 'print' in line:
            self._gen.print(line['print'])
        if 'rotate_0' in line:
            self._gen.rotate_0()
        if 'rotate_90' in line:
            self._gen.rotate_90()
        if 'rotate_180' in line:
            self._gen.rotate_180()
        if 'rotate_270' in line:
            self._gen.rotate_270()
        if 'ttf_write' in line:
            self._gen.ttf_face(line['font'], line['expansion'], line.get('pitch', 0))
            self._gen.ttf_write(line['ttf_write'], line['pos'], line.get('width'), line.get('align'))


class SG412R_Status5:
    """
    A communication class for printing when the printer of SATO is operating on STATUS 5
    
    Since the communication specification when the printer
    is operating in STATUS 5 is not disclosed, 
    this module was created by analyzing TCP / IP packet instead of manual.
    
    Since the author confirmed the operation only with SG412R-ex, 
    there is a possibility that it will not work on other models. 
    In that case, please refer to this class and implement it yourself. Welcome your post.::

        comm = SG412R_Status5()
        with comm.open("192.168.0.251", 1024):
            comm.prepare()
            # generate label...
            gen = LabelGenerator()
            with self._gen.packet_for_with():
                with self._gen.page_for_with():
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
    """
    _client = None
    def open(self, host, port):
        self._client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ret = self._client.connect_ex((host, port,))
        class CommGather:
            _comm = None
            def __init__(self, g):
                self._comm = g
            def __enter__(self):
                return self
            def __exit__(self, ex_type, ex_value, trace):
                self._comm.close()
        return CommGather(self)

    def close(self):
        ret = self._client.close()
        #print("socket closed:")

    def prepare(self):
        # initialize packet
        ret = self._client.send(bytes.fromhex('1b411b4352302c301b5a3d'))
        #print("send initialize packet:")

        # printing prepare packet
        ret = self._client.send(bytes.fromhex('2101052a2a2a2a2a03'))
        #print("printing prepare packet:")

        response = self._client.recv(4096)
        #print("received:"+str(response))

    def send(self, packets):
        self._client.send(packets)

    def finish(self):
        # printing done packet
        ret = self._client.send(bytes.fromhex('2101052a2a2a2a2a03'))
        #print("printing done packet:")

        response = self._client.recv(4096)
        #print("received:"+str(response))




