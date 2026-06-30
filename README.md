# SpellForce3_blender_model_animation_importer

Blender addon to import SpellForce 3 models (.crf) and animations (.caf) into blender. Confirmed working on blender versions 4.5.10 and 5.1.2

Based on [JA-BiA-Tools](https://github.com/sbobovyc/JA-BiA-Tools/tree/master/dist/io_scene_crf) by Stanislav Bobovych.

Install "sf3_importer.zip" like any other blender addon.

File->Import->SpellForce 3 model (.crf)/SpellForce 3 animation (.caf) to import models and animations respectively.

To import an animation, import the compatable model first.

First, try to import a model from "SpellForceThree/SpellForce3Legacy/bin_win32/characters", as SF3 Legacy comes fully unpacked. 

In order to find DLC assets, use PakInspector.exe to open "SpellForceThree\bin_exp1_win32\package.pak" and "SpellForceThree\bin_exp2_win32\package.pak" and extract the following folders into one folder:

-characters

-environment

-items

-textures

After that, pick any crf from "characters", "environment" or "items" folders.