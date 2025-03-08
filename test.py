from ai4bharat.transliteration import XlitEngine
e = XlitEngine(src_script_type="indic", beam_width=10, rescore=False)
out = e.translit_word("नमस्ते", lang_code="hi", topk=5)
print(out)
# output: ['namaste', 'namastey', 'namasthe', 'namastay', 'namste']