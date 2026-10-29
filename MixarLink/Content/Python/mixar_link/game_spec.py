"""The template game, as data: what ``game.build`` makes under /Game/Mixar/Game.

Plain Python (no ``unreal`` import) so it can be read and checked anywhere.
Each Blueprint is a parent class, member variables, functions (parameters +
Blueprint graph DSL) and event-graph DSL — the S-expression language of
Epic's EditorToolset (``BlueprintTools.get_graph_dsl_docs``).

The game mirrors Mixar Link for Godot's: the GameMode keeps the rules, driven
by the ``mixar_role`` tags ``place`` puts on actors —

- ``pickup``: spins; touching it collects it; all collected opens the doors;
- ``door``: opens (``mixar_pivot`` hinge_* swings 90° about that Blender
  axis, slide_* moves it its own length plus 25 cm);
- ``goal``: wins once the doors are open;
- ``hazard`` / ``enemy``: costs a life (respawn); with slide_* it patrols 4 m;
- ``checkpoint``: the respawn point from then on;
- ``spawn``: where the player starts, hidden in game;
- ``trigger``: reports ``trigger`` when the player walks in.

Falling 25 m below the respawn point costs a life too. Custom Blueprints talk
to the rules through the GameMode's ``OnMixarEvent(Event, Source)`` (pickup,
hazard, checkpoint, goal, lose, restart) and report their own values with
``ReportState(Key, Value)``; Mixar's playtests read both.
"""

# Template ids (the GameMode's ``Template`` variable).
TEMPLATES = {"third_person": 0, "top_down": 1, "platformer": 2}

ACTOR = "/Script/Engine.Actor"
CHARACTER = "/Script/Engine.Character"
INPUT_ACTION = "/Script/EnhancedInput.InputAction"

# Player capsule (the template Mannequin): radius and half height, cm. A
# volume counts as touched when the capsule overlaps it.
_REACH = "(Math|Vector|MakeVector :X (+ 34.0 Grow) :Y (+ 34.0 Grow) :Z (+ 90.0 Grow))"

GAME_MODE = {
    "name": "BP_MixarGameMode",
    "parent": "/Game/ThirdPerson/Blueprints/BP_ThirdPersonGameMode.BP_ThirdPersonGameMode_C",
    "variables": [
        ("Template", "int"), ("Total", "int"), ("Collected", "int"), ("Deaths", "int"),
        ("Won", "bool"), ("Lost", "bool"), ("DoorsOpen", "bool"), ("DoorT", "float"),
        ("Clock", "float"), ("Respawn", "Vector"),
        ("DoorStart", "Transform", "ARRAY"), ("HazardStart", "Vector", "ARRAY"),
        ("State", "string", "MAP"),
    ],
    "object_variables": [
        ("Player", CHARACTER, None),
        ("Pickups", ACTOR, "ARRAY"), ("Doors", ACTOR, "ARRAY"), ("Hazards", ACTOR, "ARRAY"),
        ("Goals", ACTOR, "ARRAY"), ("Checkpoints", ACTOR, "ARRAY"), ("Triggers", ACTOR, "ARRAY"),
        ("Inside", ACTOR, "ARRAY"),
    ],
    # (name, [(param, type | class path, is_object)], [(output, type)], dsl)
    "functions": [
        ("MixarTouches", [("Target", ACTOR, True), ("Grow", "float", False)], [("Result", "bool")], f"""
(fn MixarTouches (Target Grow)
  (bind (origin extent) (Collision|GetActorBounds :self Target :bOnlyCollidingComponents false
                                                  :bIncludeFromChildActors true))
  (bind at (Transformation|GetActorLocation :self (Variables|Default|GetPlayer)))
  (return (Math|Geometry|IsPointinBox at origin (+ extent {_REACH}))))
"""),
        ("MixarPivotAxis", [("Target", ACTOR, True), ("Slide", "bool", False)], [("Axis", "Vector")], """
(fn MixarPivotAxis (Target Slide)
  (if Slide
    (if (Actor|ActorHasTag :self Target :Tag "mixar_pivot=slide_x")
      (return (Math|Vector|MakeVector :X 1.0 :Y 0.0 :Z 0.0)))
    (if (Actor|ActorHasTag :self Target :Tag "mixar_pivot=slide_y")
      (return (Math|Vector|MakeVector :X 0.0 :Y -1.0 :Z 0.0)))
    (if (Actor|ActorHasTag :self Target :Tag "mixar_pivot=slide_z")
      (return (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 1.0)))
    (return (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 0.0)))
  (if (Actor|ActorHasTag :self Target :Tag "mixar_pivot=hinge_x")
    (return (Math|Vector|MakeVector :X 1.0 :Y 0.0 :Z 0.0)))
  (if (Actor|ActorHasTag :self Target :Tag "mixar_pivot=hinge_y")
    (return (Math|Vector|MakeVector :X 0.0 :Y -1.0 :Z 0.0)))
  (return (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 1.0)))
"""),
        ("MixarOpenDoors", [], [], """
(fn MixarOpenDoors ()
  (if (not (Variables|Default|GetDoorsOpen))
    (Variables|Default|SetDoorsOpen true)
    (Variables|Default|SetDoorT 0.0)
    (Development|PrintString :InString "[Mixar Game] doors open" :bPrintToScreen false)))
"""),
        ("MixarRespawnPlayer", [], [], """
(fn MixarRespawnPlayer ()
  (bind player (Variables|Default|GetPlayer))
  (Transformation|SetActorLocation :self player :NewLocation (Variables|Default|GetRespawn)
                                   :bSweep false :bTeleport true)
  (Components|Movement|StopMovementImmediately :self (Pawn|GetMovementComponent :self player)))
"""),
        ("MixarCamera", [], [], """
(fn MixarCamera ()
  (bind player (Variables|Default|GetPlayer))
  (bind template (Variables|Default|GetTemplate))
  (if (> template 0)
    (bind arm (Utilities|Casting|CastToSpringArmComponent
                :Object (Actor|GetComponentbyClass :self player :ComponentClass "/Script/Engine.SpringArmComponent"))
      (:then
        (Class|SpringArmComponent|SetUsePawnControlRotation :self arm :bUsePawnControlRotation false)
        (Class|SpringArmComponent|SetDoCollisionTest :self arm :bDoCollisionTest false)
        (Transformation|SetAbsolute :self arm :bNewAbsoluteLocation false :bNewAbsoluteRotation true
                                    :bNewAbsoluteScale false)
        (if (== template 1)
          (Class|SpringArmComponent|SetTargetArmLength :self arm :TargetArmLength 1400.0)
          (Transformation|SetWorldRotation :self arm
             :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch -60.0 :Yaw -90.0) :bSweep false :bTeleport true)
          (else
            (Class|SpringArmComponent|SetTargetArmLength :self arm :TargetArmLength 1200.0)
            (Transformation|SetWorldRotation :self arm
               :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch -10.0 :Yaw -90.0) :bSweep false :bTeleport true)
            (bind moves (Pawn|GetMovementComponent :self player))
            (Components|Movement|Planar|SetPlaneConstraintNormal :self moves
               :PlaneNormal (Math|Vector|MakeVector :X 0.0 :Y 1.0 :Z 0.0))
            (Components|Movement|Planar|SetPlaneConstraintOrigin :self moves
               :PlaneOrigin (Variables|Default|GetRespawn))
            (Components|Movement|Planar|SetPlaneConstraintEnabled :self moves :bEnabled true))))
      (:CastFailed))))
"""),
        ("MixarInject", [("Action", INPUT_ACTION, True), ("Value", "Vector", False)], [], """
(fn MixarInject (Action Value)
  (Input|InjectInputVectorforAction
    :self (PlayerController|LocalPlayerSubsystems|GetEnhancedInputLocalPlayerSubsystem
            :PlayerController (Game|GetPlayerController :PlayerIndex 0))
    :Action Action :Value Value))
"""),
        ("ReportState", [("Key", "string", False), ("Value", "string", False)], [], """
(fn ReportState (Key Value)
  (Utilities|Map|Add (Variables|Default|GetState) Key Value))
"""),
        ("OnMixarEvent", [("Event", "string", False), ("Source", ACTOR, True)], [], """
(fn OnMixarEvent (Event Source)
  (if (Utilities|String|EqualExactly(String) Event "pickup")
    (Variables|Default|SetCollected (+ (Variables|Default|GetCollected) 1))
    (Actor|DestroyActor :self Source)
    (if (>= (Variables|Default|GetCollected) (Variables|Default|GetTotal))
      (CallFunction|MixarOpenDoors))
    (elif (Utilities|String|EqualExactly(String) Event "hazard")
      (Variables|Default|SetDeaths (+ (Variables|Default|GetDeaths) 1))
      (CallFunction|MixarRespawnPlayer)
      (elif (Utilities|String|EqualExactly(String) Event "checkpoint")
        (Variables|Default|SetRespawn (+ (Transformation|GetActorLocation :self Source)
                                         (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 100.0)))
        (elif (Utilities|String|EqualExactly(String) Event "goal")
          (if (and (Variables|Default|GetDoorsOpen)
                   (and (not (Variables|Default|GetWon)) (not (Variables|Default|GetLost))))
            (Variables|Default|SetWon true)
            (Development|PrintString :InString "[Mixar Game] won" :bPrintToScreen false))
          (elif (Utilities|String|EqualExactly(String) Event "lose")
            (if (and (not (Variables|Default|GetWon)) (not (Variables|Default|GetLost)))
              (Variables|Default|SetLost true)
              (Development|PrintString :InString "[Mixar Game] lost" :bPrintToScreen false))
            (elif (Utilities|String|EqualExactly(String) Event "restart")
              (Development|ExecuteConsoleCommand :Command "RestartLevel"))))))))
"""),
    ],
    "events": """
(event EventBeginPlay
  (Variables|Default|SetPlayer (Game|GetPlayerCharacter :PlayerIndex 0))
  (bind pickups (Actor|GetAllActorswithTag :Tag "mixar_role=pickup"))
  (Variables|Default|SetPickups pickups)
  (Variables|Default|SetTotal (Utilities|Array|Length pickups))
  (for p pickups
    (Collision|SetActorEnableCollision :self p :bNewActorEnableCollision false))
  (bind doors (Actor|GetAllActorswithTag :Tag "mixar_role=door"))
  (Variables|Default|SetDoors doors)
  (for d doors
    (Utilities|Array|Add (Variables|Default|GetDoorStart) (Transformation|GetActorTransform :self d)))
  (bind hazards (Actor|GetAllActorswithTag :Tag "mixar_role=hazard"))
  (Utilities|Array|AppendArray hazards (Actor|GetAllActorswithTag :Tag "mixar_role=enemy"))
  (Variables|Default|SetHazards hazards)
  (for h hazards
    (Utilities|Array|Add (Variables|Default|GetHazardStart) (Transformation|GetActorLocation :self h)))
  (bind goals (Actor|GetAllActorswithTag :Tag "mixar_role=goal"))
  (Variables|Default|SetGoals goals)
  (for g goals
    (Collision|SetActorEnableCollision :self g :bNewActorEnableCollision false))
  (bind checkpoints (Actor|GetAllActorswithTag :Tag "mixar_role=checkpoint"))
  (Variables|Default|SetCheckpoints checkpoints)
  (for c checkpoints
    (Collision|SetActorEnableCollision :self c :bNewActorEnableCollision false))
  (bind triggers (Actor|GetAllActorswithTag :Tag "mixar_role=trigger"))
  (Variables|Default|SetTriggers triggers)
  (for t triggers
    (Collision|SetActorEnableCollision :self t :bNewActorEnableCollision false))
  (Variables|Default|SetRespawn (Transformation|GetActorLocation :self (Variables|Default|GetPlayer)))
  (bind spawns (Actor|GetAllActorswithTag :Tag "mixar_role=spawn"))
  (for s spawns
    (Collision|SetActorEnableCollision :self s :bNewActorEnableCollision false)
    (Rendering|SetActorHiddenInGame :self s :bNewHidden true))
  (if (> (Utilities|Array|Length spawns) 0)
    (Variables|Default|SetRespawn (+ (Transformation|GetActorLocation :self (Utilities|Array|Get(acopy) spawns 0))
                                     (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 100.0)))
    (CallFunction|MixarRespawnPlayer))
  (CallFunction|MixarCamera)
  (if (== (Variables|Default|GetTotal) 0)
    (CallFunction|MixarOpenDoors))
  (Development|PrintString :InString (Utilities|String|Append "[Mixar Game] started: "
                                        (Utilities|String|ToString(Integer) (Variables|Default|GetTotal)))
                           :bPrintToScreen false))

(event EventTick (DeltaSeconds)
  (Variables|Default|SetClock (+ (Variables|Default|GetClock) DeltaSeconds))
  ; top_down / platformer: north (Blender +Y) stays up the screen whatever the look input does
  (if (> (Variables|Default|GetTemplate) 0)
    (Pawn|SetControlRotation :self (Game|GetPlayerController :PlayerIndex 0)
                             :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw -90.0)))
  (for p (Variables|Default|GetPickups)
    (Utilities|IsValid p
      (:"Is Valid"
        (Transformation|AddActorWorldRotation :self p
           :DeltaRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw (* DeltaSeconds 86.0))
           :bSweep false :bTeleport true)
        (if (and (not (Variables|Default|GetWon)) (CallFunction|MixarTouches :Target p :Grow 30.0))
          (CallFunction|OnMixarEvent :Event "pickup" :Source p)))
      (:"Is Not Valid")))
  (bind doors (Variables|Default|GetDoors))
  (if (and (Variables|Default|GetDoorsOpen) (< (Variables|Default|GetDoorT) 1.0))
    (Variables|Default|SetDoorT (Math|Float|Min(Float) (+ (Variables|Default|GetDoorT) (/ DeltaSeconds 1.2)) 1.0))
    (bind ease (- 0.5 (* 0.5 (Math|Trig|Cos(Degrees) (* (Variables|Default|GetDoorT) 180.0)))))
    (for i (range (Utilities|Array|Length doors))
      (bind door (Utilities|Array|Get(acopy) doors i))
      (bind start (Utilities|Array|Get(acopy) (Variables|Default|GetDoorStart) i))
      (bind slide (CallFunction|MixarPivotAxis :Target door :Slide true))
      (if (> (Math|Vector|VectorLength slide) 0.0)
        (bind (origin extent) (Collision|GetActorBounds :self door :bOnlyCollidingComponents false
                                                        :bIncludeFromChildActors true))
        (bind span (+ 25.0 (* 2.0 (Math|Float|Absolute(Float) (Math|Vector|DotProduct extent slide)))))
        (Transformation|SetActorLocation :self door
           :NewLocation (+ (.location start) (* (Math|Vector|RotateVector slide (.rotation start)) (* span ease)))
           :bSweep false :bTeleport true)
        (else
          (bind hinge (* (CallFunction|MixarPivotAxis :Target door :Slide false) (* 90.0 ease)))
          (Transformation|SetActorRotation :self door
             :NewRotation (Math|Rotator|CombineRotators
                            (Math|Rotator|MakeRotator :Roll (.x hinge) :Pitch (.y hinge) :Yaw (.z hinge))
                            (.rotation start))
             :bTeleportPhysics true)))))
  (bind hazards (Variables|Default|GetHazards))
  (bind swing (- 0.5 (* 0.5 (Math|Trig|Cos(Degrees) (* (Variables|Default|GetClock) 67.5)))))
  (for i (range (Utilities|Array|Length hazards))
    (bind hazard (Utilities|Array|Get(acopy) hazards i))
    (bind patrol (CallFunction|MixarPivotAxis :Target hazard :Slide true))
    (if (> (Math|Vector|VectorLength patrol) 0.0)
      (Transformation|SetActorLocation :self hazard
         :NewLocation (+ (Utilities|Array|Get(acopy) (Variables|Default|GetHazardStart) i) (* patrol (* 400.0 swing)))
         :bSweep false :bTeleport true))
    (if (and (not (Variables|Default|GetWon)) (CallFunction|MixarTouches :Target hazard :Grow 15.0))
      (CallFunction|OnMixarEvent :Event "hazard" :Source hazard)))
  (for g (Variables|Default|GetGoals)
    (if (CallFunction|MixarTouches :Target g :Grow 10.0)
      (CallFunction|OnMixarEvent :Event "goal" :Source g)))
  (for c (Variables|Default|GetCheckpoints)
    (if (CallFunction|MixarTouches :Target c :Grow 10.0)
      (CallFunction|OnMixarEvent :Event "checkpoint" :Source c)))
  (for t (Variables|Default|GetTriggers)
    (bind inside (Utilities|Array|ContainsItem (Variables|Default|GetInside) t))
    (if (CallFunction|MixarTouches :Target t :Grow 10.0)
      (if (not inside)
        (Utilities|Array|Add (Variables|Default|GetInside) t)
        (CallFunction|OnMixarEvent :Event "trigger" :Source t))
      (else
        (if inside
          (Utilities|Array|RemoveItem (Variables|Default|GetInside) t)))))
  (if (< (.z (Transformation|GetActorLocation :self (Variables|Default|GetPlayer)))
         (- (.z (Variables|Default|GetRespawn)) 2500.0))
    (CallFunction|OnMixarEvent :Event "hazard" :Source (Variables|Default|GetPlayer))))
""",
}

# The HUD: collected count top left, the win / lose banner in the middle.
HUD = {
    "name": "BP_MixarHUD",
    "parent": "/Script/Engine.HUD",
    "events": """
(event EventReceiveDrawHUD (SizeX SizeY)
  (bind gm (Utilities|Casting|CastToBP_MixarGameMode :Object (Game|GetGameMode))
    (:then
      (bind total (Class|BPMixarGameMode|GetTotal :self gm))
      (if (> total 0)
        (HUD|DrawText :self self
          :Text (Utilities|String|Append (Utilities|String|Append "Collected "
                  (Utilities|String|ToString(Integer) (Class|BPMixarGameMode|GetCollected :self gm)))
                  (Utilities|String|Append " / " (Utilities|String|ToString(Integer) total)))
          :TextColor (Math|Color|MakeColor :R 1.0 :G 1.0 :B 1.0 :A 1.0)
          :ScreenX 24.0 :ScreenY 16.0 :Scale 2.0 :bScalePosition false))
      (bind lost (Class|BPMixarGameMode|GetLost :self gm))
      (if (or (Class|BPMixarGameMode|GetWon :self gm) lost)
        (bind banner (Utilities|String|SelectString :A "Game over" :B "You win!" :bPickA lost))
        (bind (w h) (HUD|GetTextSize :self self :Text banner :Scale 4.0))
        (HUD|DrawText :self self :Text banner
          :TextColor (Math|Color|MakeColor :R 1.0 :G 0.85 :B 0.2 :A 1.0)
          :ScreenX (/ (- SizeX w) 2.0) :ScreenY (/ (- SizeY h) 2.0) :Scale 4.0 :bScalePosition false)))
    (:CastFailed)))
""",
}
