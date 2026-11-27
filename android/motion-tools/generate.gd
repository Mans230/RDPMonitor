extends SceneTree
func _initialize():
    var control = Control.new()
    root.add_child(control)
    control.modulate.a = 0.0
    var tween = create_tween()
    tween.pause()
    tween.tween_property(control, "modulate:a", 1.0, 1.0).set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
    var samples = [0.0]
    for index in range(60):
        tween.custom_step(1.0 / 60.0)
        samples.append(snappedf(control.modulate.a, 0.000001))
    var file = FileAccess.open("res://../app/src/main/res/raw/motion_pulse.json", FileAccess.WRITE)
    file.store_string(JSON.stringify({"schema":1,"producer":"godot@4.7.2","samples":samples}))
    file.close()
    print("Generated ", samples.size(), " Godot signal samples.")
    quit()
