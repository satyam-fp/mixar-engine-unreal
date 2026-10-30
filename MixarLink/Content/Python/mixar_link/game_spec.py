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
  an enemy without one chases the player who comes within 9 m of its post,
  turned to face where it goes, and walks back when they leave;
- ``checkpoint``: the respawn point from then on;
- ``spawn``: where the player starts, hidden in game;
- ``trigger``: reports ``trigger`` when the player walks in.

- ``player``: a rigged humanoid the player plays as (its mesh replaces the
  template Mannequin at start and its idle / run / fall clips, retargeted from
  the Mannequin's by ``place``, play as the player moves; the stand-in hides).

Falling 25 m below the respawn point costs a life too. Custom Blueprints talk
to the rules through the GameMode's ``OnMixarEvent(Event, Source)`` (pickup,
hazard, checkpoint, goal, lose, restart) and report their own values with
``ReportState(Key, Value)``; Mixar's playtests read both.

The game sounds and shows its events (``MixarFx``: a chime and a gold burst
for a pickup, a hit and a red flash for a death, the door grinding open, a
fanfare for the win), plays wind and a music loop, and its HUD shows the
level's title card, the count, the time and an end screen. The level's
``BP_MixarGameInfo`` actor holds the title, the objective and whether music
and wind play (``new_scene`` makes it; ``set_property`` edits it).
"""

# Template ids (the GameMode's ``Template`` variable).
TEMPLATES = {"third_person": 0, "top_down": 1, "platformer": 2}

ACTOR = "/Script/Engine.Actor"
CHARACTER = "/Script/Engine.Character"
INPUT_ACTION = "/Script/EnhancedInput.InputAction"
ANIM = "/Script/Engine.AnimSequence"

# Player capsule (the template Mannequin): radius and half height, cm. A
# volume counts as touched when the capsule overlaps it.
_REACH = "(Math|Vector|MakeVector :X (+ 34.0 Grow) :Y (+ 34.0 Grow) :Z (+ 90.0 Grow))"

ROBOTO = "/Engine/EngineFonts/RobotoDistanceField.RobotoDistanceField"
GAME_INFO_CLASS = "/Game/Mixar/Game/BP_MixarGameInfo.BP_MixarGameInfo_C"

# The level's settings for the template game: one per level.
GAME_INFO = {
    "name": "BP_MixarGameInfo",
    "parent": ACTOR,
    "variables": [("Title", "string"), ("Objective", "string"), ("Music", "bool"), ("Ambience", "bool")],
    # A player character's clips (place sets them): idle, run, in the air.
    "object_variables": [("IdleAnim", ANIM, None), ("RunAnim", ANIM, None), ("FallAnim", ANIM, None)],
    "editable": True,
    "defaults": {"Music": True, "Ambience": True},
}

GAME_MODE = {
    "name": "BP_MixarGameMode",
    "parent": "/Game/ThirdPerson/Blueprints/BP_ThirdPersonGameMode.BP_ThirdPersonGameMode_C",
    "variables": [
        ("Template", "int"), ("Total", "int"), ("Collected", "int"), ("Deaths", "int"),
        ("Won", "bool"), ("Lost", "bool"), ("DoorsOpen", "bool"), ("DoorT", "float"),
        ("Clock", "float"), ("Respawn", "Vector"), ("PlayTime", "float"), ("LastHurt", "float"),
        ("Title", "string"), ("Objective", "string"), ("CustomBody", "bool"), ("BodyState", "int"),
        ("DoorStart", "Transform", "ARRAY"), ("HazardStart", "Vector", "ARRAY"),
        ("State", "string", "MAP"),
    ],
    "object_variables": [
        ("Player", CHARACTER, None),
        ("Pickups", ACTOR, "ARRAY"), ("Doors", ACTOR, "ARRAY"), ("Hazards", ACTOR, "ARRAY"),
        ("Goals", ACTOR, "ARRAY"), ("Checkpoints", ACTOR, "ARRAY"), ("Triggers", ACTOR, "ARRAY"),
        ("Inside", ACTOR, "ARRAY"),
        ("IdleAnim", ANIM, None), ("RunAnim", ANIM, None), ("FallAnim", ANIM, None),
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
    (CallFunction|MixarFx :Event "door" :Where (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 0.0))
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
        ("MixarPlayAs", [], [], """
(fn MixarPlayAs ()
  ; a placed mixar_role=player character lends the player its mesh; its clips
  ; (the game info's) play by the player's movement (MixarAnimateBody)
  (bind stands (Actor|GetAllActorswithTag :Tag "mixar_role=player"))
  (if (> (Utilities|Array|Length stands) 0)
    (bind stand (Utilities|Casting|CastToSkeletalMeshActor :Object (Utilities|Array|Get(acopy) stands 0))
      (:then
        (bind from (Class|SkeletalMeshActor|GetSkeletalMeshComponent :self stand))
        (Components|SkeletalMesh|SetSkeletalMeshAsset :self (Class|Character|GetMesh :self (Variables|Default|GetPlayer))
           :NewMesh (Components|SkeletalMesh|GetSkeletalMeshAsset :self from))
        (Variables|Default|SetCustomBody true)
        (Variables|Default|SetBodyState -1)
        (Rendering|SetActorHiddenInGame :self stand :bNewHidden true)
        (Collision|SetActorEnableCollision :self stand :bNewActorEnableCollision false))
      (:CastFailed))))
"""),
        ("MixarBodyState", [], [("State", "int")], """
(fn MixarBodyState ()
  (bind player (Variables|Default|GetPlayer))
  (if (Movement|IsFalling :self (Pawn|GetMovementComponent :self player))
    (return 2))
  (if (> (Math|Vector|VectorLengthXY (Transformation|GetVelocity :self player)) 40.0)
    (return 1))
  (return 0))
"""),
        ("MixarAnimateBody", [], [], """
(fn MixarAnimateBody ()
  (bind body (Class|Character|GetMesh :self (Variables|Default|GetPlayer)))
  (bind want (CallFunction|MixarBodyState))
  (if (not (== want (Variables|Default|GetBodyState)))
    (Variables|Default|SetBodyState want)
    (if (== want 2)
      (Components|Animation|PlayAnimation :self body :NewAnimToPlay (Variables|Default|GetFallAnim) :bLooping true)
      (elif (== want 1)
        (Components|Animation|PlayAnimation :self body :NewAnimToPlay (Variables|Default|GetRunAnim) :bLooping true)
        (else
          (Components|Animation|PlayAnimation :self body :NewAnimToPlay (Variables|Default|GetIdleAnim)
                                              :bLooping true))))))
"""),
        ("MixarReadInfo", [], [], """
(fn MixarReadInfo ()
  ; the level's BP_MixarGameInfo: title card, objective, music and wind
  (bind info (Utilities|Casting|CastToBP_MixarGameInfo
               :Object (Actor|GetActorOfClass :ActorClass "/Game/Mixar/Game/BP_MixarGameInfo.BP_MixarGameInfo_C"))
    (:then
      (Variables|Default|SetTitle (Class|BPMixarGameInfo|GetTitle :self info))
      (Variables|Default|SetObjective (Class|BPMixarGameInfo|GetObjective :self info))
      (Variables|Default|SetIdleAnim (Class|BPMixarGameInfo|GetIdleAnim :self info))
      (Variables|Default|SetRunAnim (Class|BPMixarGameInfo|GetRunAnim :self info))
      (Variables|Default|SetFallAnim (Class|BPMixarGameInfo|GetFallAnim :self info))
      (CallFunction|MixarAmbience :Music (Class|BPMixarGameInfo|GetMusic :self info)
                                  :Wind (Class|BPMixarGameInfo|GetAmbience :self info)))
    (:CastFailed
      (CallFunction|MixarAmbience :Music true :Wind true))))
"""),
        ("MixarStep", [("Mover", ACTOR, True), ("Toward", "Vector", False), ("Speed", "float", False),
                       ("Delta", "float", False)], [], """
(fn MixarStep (Mover Toward Speed Delta)
  ; move flat toward a point, facing the way it goes (its mesh faces Blender -Y)
  (bind at (Transformation|GetActorLocation :self Mover))
  (bind flat (Math|Vector|MakeVector :X (- (.x Toward) (.x at)) :Y (- (.y Toward) (.y at)) :Z 0.0))
  (if (> (Math|Vector|VectorLength flat) 30.0)
    (bind dir (Math|Vector|Normalize flat))
    (Transformation|SetActorLocation :self Mover :NewLocation (+ at (* dir (* Speed Delta)))
                                     :bSweep false :bTeleport true)
    (Transformation|SetActorRotation :self Mover
       :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0
                      :Yaw (- (Math|Trig|Atan2(Degrees) (.y dir) (.x dir)) 90.0))
       :bTeleportPhysics true)))
"""),
        ("MixarChase", [("Enemy", ACTOR, True), ("Home", "Vector", False), ("Delta", "float", False)], [], """
(fn MixarChase (Enemy Home Delta)
  (bind target (Transformation|GetActorLocation :self (Variables|Default|GetPlayer)))
  (bind offset (- target Home))
  (if (and (not (Variables|Default|GetWon))
           (< (Math|Vector|VectorLengthXY offset) 900.0))
    (CallFunction|MixarStep :Mover Enemy :Toward target :Speed 280.0 :Delta Delta)
    (else
      (CallFunction|MixarStep :Mover Enemy :Toward Home :Speed 180.0 :Delta Delta))))
"""),
        ("ReportState", [("Key", "string", False), ("Value", "string", False)], [], """
(fn ReportState (Key Value)
  (Utilities|Map|Add (Variables|Default|GetState) Key Value))
"""),
        ("OnMixarEvent", [("Event", "string", False), ("Source", ACTOR, True)], [], """
(fn OnMixarEvent (Event Source)
  (if (Utilities|String|EqualExactly(String) Event "pickup")
    (Variables|Default|SetCollected (+ (Variables|Default|GetCollected) 1))
    (CallFunction|MixarFx :Event "pickup" :Where (Transformation|GetActorLocation :self Source))
    (Actor|DestroyActor :self Source)
    (if (>= (Variables|Default|GetCollected) (Variables|Default|GetTotal))
      (CallFunction|MixarOpenDoors))
    (elif (Utilities|String|EqualExactly(String) Event "hazard")
      (Variables|Default|SetDeaths (+ (Variables|Default|GetDeaths) 1))
      (Variables|Default|SetLastHurt (Variables|Default|GetClock))
      (CallFunction|MixarFx :Event "hurt"
        :Where (Transformation|GetActorLocation :self (Variables|Default|GetPlayer)))
      (CallFunction|MixarRespawnPlayer)
      (elif (Utilities|String|EqualExactly(String) Event "checkpoint")
        (bind spot (+ (Transformation|GetActorLocation :self Source) (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 100.0)))
        (if (> (Math|Vector|VectorLength (- spot (Variables|Default|GetRespawn))) 10.0)
          (CallFunction|MixarFx :Event "checkpoint" :Where spot))
        (Variables|Default|SetRespawn spot)
        (elif (Utilities|String|EqualExactly(String) Event "goal")
          (if (and (Variables|Default|GetDoorsOpen)
                   (and (not (Variables|Default|GetWon)) (not (Variables|Default|GetLost))))
            (Variables|Default|SetWon true)
            (CallFunction|MixarFx :Event "win" :Where (Transformation|GetActorLocation :self Source))
            (Development|PrintString :InString "[Mixar Game] won" :bPrintToScreen false))
          (elif (Utilities|String|EqualExactly(String) Event "lose")
            (if (and (not (Variables|Default|GetWon)) (not (Variables|Default|GetLost)))
              (Variables|Default|SetLost true)
              (CallFunction|MixarFx :Event "hurt"
                :Where (Transformation|GetActorLocation :self (Variables|Default|GetPlayer)))
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
  (CallFunction|MixarReadInfo)
  (CallFunction|MixarPlayAs)
  (if (== (Variables|Default|GetTotal) 0)
    (CallFunction|MixarOpenDoors))
  (Development|PrintString :InString (Utilities|String|Append "[Mixar Game] started: "
                                        (Utilities|String|ToString(Integer) (Variables|Default|GetTotal)))
                           :bPrintToScreen false))

(event EventTick (DeltaSeconds)
  (Variables|Default|SetClock (+ (Variables|Default|GetClock) DeltaSeconds))
  (if (and (not (Variables|Default|GetWon)) (not (Variables|Default|GetLost)))
    (Variables|Default|SetPlayTime (+ (Variables|Default|GetPlayTime) DeltaSeconds)))
  (if (Variables|Default|GetCustomBody)
    (CallFunction|MixarAnimateBody))
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
         :bSweep false :bTeleport true)
      (elif (Actor|ActorHasTag :self hazard :Tag "mixar_role=enemy")
        (CallFunction|MixarChase :Enemy hazard :Home (Utilities|Array|Get(acopy) (Variables|Default|GetHazardStart) i)
                                 :Delta DeltaSeconds)))
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


# (event, sound, volume, effect) for MixarFx.
FX_EVENTS = (("pickup", "S_MixarPickup", 0.8, "NS_MixarPickup"), ("hurt", "S_MixarHurt", 0.9, "NS_MixarHurt"),
             ("checkpoint", "S_MixarCheckpoint", 0.7, ""), ("door", "S_MixarDoor", 0.8, ""),
             ("win", "S_MixarWin", 0.9, "NS_MixarWin"))


def fx_functions(assets: dict) -> list:
    """``MixarFx(Event, Where)`` and ``MixarAmbience(Music, Wind)`` over the
    sounds and effects ``game_assets`` made ({name: object path}); a missing
    one is left out, so the game still builds and plays without it."""
    branches = []
    for event, sound, volume, effect in FX_EVENTS:
        body = []
        if sound in assets:
            body.append(f'(Audio|PlaySound2D :Sound "{assets[sound]}" :VolumeMultiplier {volume})')
        if effect in assets:
            body.append(f'(Niagara|SpawnSystematLocation :SystemTemplate "{assets[effect]}" :Location Where)')
        if body:
            branches.append((event, body))
    fx = ""
    for i, (event, body) in reversed(list(enumerate(branches))):
        tail = f"\n    {fx}" if fx else ""
        fx = (f'({"if" if i == 0 else "elif"} (Utilities|String|EqualExactly(String) Event "{event}")\n    '
              + "\n    ".join(body) + tail + ")")
    fx = fx or '(Development|PrintString :InString Event :bPrintToScreen false)'
    ambience = []
    if "S_MixarWind" in assets:
        ambience.append(f'(if Wind (Audio|SpawnSound2D :Sound "{assets["S_MixarWind"]}" :VolumeMultiplier 0.35))')
    if "S_MixarMusic" in assets:
        ambience.append(f'(if Music (Audio|SpawnSound2D :Sound "{assets["S_MixarMusic"]}" :VolumeMultiplier 0.3))')
    ambience = ambience or ['(Development|PrintString :InString "no ambience" :bPrintToScreen false)']
    return [
        ("MixarFx", [("Event", "string", False), ("Where", "Vector", False)], [],
         f"(fn MixarFx (Event Where)\n  {fx})\n"),
        ("MixarAmbience", [("Music", "bool", False), ("Wind", "bool", False)], [],
         "(fn MixarAmbience (Music Wind)\n  " + "\n  ".join(ambience) + ")\n"),
    ]


def _text(text: str, x: str, y: str, scale: float, color: str) -> str:
    return (f'(HUD|DrawText :self self :Text {text} :TextColor {color} :ScreenX {x} :ScreenY {y} '
            f':Font "{ROBOTO}" :Scale {scale} :bScalePosition false)')


def _rect(color: str, x: str, y: str, w: str, h: str) -> str:
    return f"(HUD|DrawRect :self self :RectColor {color} :ScreenX {x} :ScreenY {y} :ScreenW {w} :ScreenH {h})"


def _rgba(r, g, b, a) -> str:
    return f"(Math|Color|MakeColor :R {r} :G {g} :B {b} :A {a})"


def _size(var: str, text: str, scale: float) -> str:
    return f'(bind ({var}w {var}h) (HUD|GetTextSize :self self :Text {text} :Font "{ROBOTO}" :Scale {scale}))'


_COUNT = ('(Utilities|String|Append (Utilities|String|Append "Collected  " '
          '(Utilities|String|ToString(Integer) (Class|BPMixarGameMode|GetCollected :self gm))) '
          '(Utilities|String|Append " / " (Utilities|String|ToString(Integer) total)))')
_TIME = "(CallFunction|MixarClockText :Seconds (Class|BPMixarGameMode|GetPlayTime :self gm))"
_STATS = ('(Utilities|String|Append (Utilities|String|Append "Time  " ' + _TIME + ') '
          '(Utilities|String|Append "      Deaths  " '
          '(Utilities|String|ToString(Integer) (Class|BPMixarGameMode|GetDeaths :self gm))))')
_FLASH = _rgba(0.75, 0.02, 0.0, "(* 0.4 (- 1.0 (/ since 0.45)))")
_PANEL = _rgba(0.0, 0.0, 0.0, 0.45)

# The HUD: the level's title card, the collected count and the time, a red
# flash on a hit, and an end screen with the time and the deaths.
HUD = {
    "name": "BP_MixarHUD",
    "parent": "/Script/Engine.HUD",
    "functions": [
        ("MixarClockText", [("Seconds", "float", False)], [("Text", "string")], """
(fn MixarClockText (Seconds)
  (bind total (Math|Float|Floor Seconds))
  (bind secs (Math|Integer|%(Integer) total 60))
  (bind padded (Utilities|String|ToString(Integer) secs))
  (return (Utilities|String|Append
            (Utilities|String|Append (Utilities|String|ToString(Integer) (/ total 60)) ":")
            (Utilities|String|SelectString :A (Utilities|String|Append "0" padded) :B padded :bPickA (< secs 10)))))
"""),
    ],
    "events": f"""
(event EventReceiveDrawHUD (SizeX SizeY)
  (bind gm (Utilities|Casting|CastToBP_MixarGameMode :Object (Game|GetGameMode))
    (:then
      (bind clock (Class|BPMixarGameMode|GetClock :self gm))
      (bind won (Class|BPMixarGameMode|GetWon :self gm))
      (bind lost (Class|BPMixarGameMode|GetLost :self gm))
      (bind total (Class|BPMixarGameMode|GetTotal :self gm))
      (bind hurt (Class|BPMixarGameMode|GetLastHurt :self gm))
      (bind since (- clock hurt))
      (if (and (> hurt 0.0) (< since 0.45))
        {_rect(_FLASH, "0.0", "0.0", "SizeX", "SizeY")})
      (if (> total 0)
        {_rect(_PANEL, "24.0", "20.0", "250.0", "52.0")}
        {_text(_COUNT, "42.0", "30.0", 1.4, _rgba(1.0, 0.86, 0.45, 1.0))})
      {_rect(_PANEL, "(- SizeX 164.0)", "20.0", "140.0", "52.0")}
      {_text(_TIME, "(- SizeX 140.0)", "30.0", 1.4, _rgba(1.0, 1.0, 1.0, 1.0))}
      (bind title (Class|BPMixarGameMode|GetTitle :self gm))
      (if (and (< clock 5.0) (not (Utilities|String|IsEmpty title)))
        (bind fade (Math|Float|Min(Float) (- 5.0 clock) 1.0))
        {_size("t", "title", 3.0)}
        {_text("title", "(/ (- SizeX tw) 2.0)", "(* SizeY 0.26)", 3.0, _rgba(1.0, 0.82, 0.4, "fade"))}
        (bind objective (Class|BPMixarGameMode|GetObjective :self gm))
        {_size("o", "objective", 1.4)}
        {_text("objective", "(/ (- SizeX ow) 2.0)", "(+ (* SizeY 0.26) (+ th 14.0))", 1.4,
               _rgba(1.0, 1.0, 1.0, "fade"))})
      (if (or won lost)
        {_rect(_rgba(0.0, 0.0, 0.0, 0.5), "0.0", "0.0", "SizeX", "SizeY")}
        (bind banner (Utilities|String|SelectString :A "Game over" :B "You win!" :bPickA lost))
        {_size("b", "banner", 4.0)}
        {_text("banner", "(/ (- SizeX bw) 2.0)", "(- (/ SizeY 2.0) bh)", 4.0, _rgba(1.0, 0.82, 0.3, 1.0))}
        (bind stats {_STATS})
        {_size("s", "stats", 1.5)}
        {_text("stats", "(/ (- SizeX sw) 2.0)", "(+ (/ SizeY 2.0) 16.0)", 1.5, _rgba(1.0, 1.0, 1.0, 1.0))}))
    (:CastFailed)))
""",
}
