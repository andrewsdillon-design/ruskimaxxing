# ruskimaxxing
Conjugate Training Implemented - combining Undulated Training Regimen with the works of Verkhoshansky,  Siff, and Prilepin 

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Usage

```bash
ruskimaxxing 200 85              # 1RM of 200, working at 85%
```

## Tests

```bash
pytest
```

## Layout

```
src/ruskimaxxing/   package source (prilepin.py = Prilepin's chart, cli.py = entry point)
tests/              pytest suite
```
