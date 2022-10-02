## Dependencies ##

* Babel

## Installation ##

* Create a babel.cfg file in root folder:

```
# Extraction from Python files
[python: **.py]

# Extraction from Jinja2 template files
[jinja2: templates/**.**]
encoding = utf-8
```

## configuring domain for Babel (gettex) ##

pybabel compile --domain=nav --directory=locale --use-fuzzy
