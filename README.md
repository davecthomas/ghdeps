# ghdeps - Github repo language-based dependency explorer

Currently only supports listing repos with python dependencies.

# Install

```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
python3 ghdeps.py
```

# Settings - the .env file should have

```
GITHUB_TOKEN=
ORGANIZATION=
LANGUAGE=
```
