from pathlib import Path
import json
import numpy as np
from manim import Square, Circle, Transform

square=Square(side_length=2)
circle=Circle(radius=1)
transform=Transform(square,circle)
transform.begin()
frames=[]
for progress in np.linspace(0,1,31):
    transform.interpolate(float(progress))
    frame=[]
    for proportion in np.linspace(0,1,64,endpoint=False):
        point=square.point_from_proportion(float(proportion))
        frame.append([round(float((point[0]+1.4)/2.8),6),round(float((1.4-point[1])/2.8),6)])
    frames.append(frame)
output=Path(__file__).resolve().parent.parent/'app/src/main/res/raw/motion_morph.json'
output.write_text(json.dumps({'schema':1,'producer':'manim@0.22.1','frames':frames},separators=(',',':')),encoding='utf-8')
print(f'Generated {len(frames)} Manim morph frames.')
