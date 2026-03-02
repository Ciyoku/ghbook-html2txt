# ghbook-html2txt

Python tool to parse HTML book files (sampled from [GhBook](https://www.ghbook.ir/)), extracting headings, paragraphs, and notes and writing a plain-text version.

## Usage

```sh
python main.py input.html [output.txt]
```

Omitting the output path creates a `.txt` file beside the input.

The generated text uses markers such as `##` for headings, `PAGE_SEPARATOR` for page breaks, and `____________` for horizontal rules.

## Requirements

- Python 3.6+ (no extra packages)