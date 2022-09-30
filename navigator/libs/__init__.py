# import os
# import sys
# from datetime import datetime
# from pathlib import Path
# from navigator.conf import BASE_DIR
# import json


# class SafeDict(dict):
#     def __missing__(self, key):
#         return "{" + key + "}"


# def load_schema(schema_name: str, directory: Path = ""):
#     if not directory:
#         directory = BASE_DIR.joinpath("models")
#     model = Path.joinpath(directory, "{}.json".format(schema_name))
#     if model.is_file():
#         with open(model, mode="r") as jsonfile:
#             try:
#                 return json.load(jsonfile)
#             except Exception as e:
#                 raise TypeError("Empty Schema File")
