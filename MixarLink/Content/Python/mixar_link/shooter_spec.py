"""The shooter template, as data: a round-based tactical first-person shooter.

``new_scene(template="shooter")`` runs the level on ``BP_MixarShooterGameMode``
(a child of ``BP_MixarGameMode``, so playtests read the same state). Built by
``game.ensure`` beside the template game, from:

- ``BP_MixarShooterPlayer`` (child of the project's third-person character):
  first person. A view model (``View``: the player character's own mesh,
  head and legs hidden, attached to the camera so it pitches with the view)
  holds ``Gun1P``; the full body with ``Gun3P`` is what others see. Fire
  (left mouse), reload (R), walk (Shift), crouch (Ctrl); hitscan along the
  view with movement and spray spread, a recoil climb that partly recovers,
  30 / 90 ammo, armor, a third-person death camera.
- ``BP_MixarBot`` (a Character on the navigation mesh): a team bot that
  walks toward the enemy spawn or the middle, turns to the nearest enemy it
  can see, reacts after a moment, fires bursts with spread (a headshot from
  the hit height), dies with a death clip.
- ``BP_MixarShooterGameMode``: CT and T spawns (``mixar_team`` tags on
  ``spawn`` markers), rounds won by elimination (or by CT when time runs
  out), first to ``RoundsToWin``; a kill feed; ``Won`` / ``Lost`` at the
  match's end.
- ``BP_MixarShooterHUD``: crosshair that opens with spread, hit marker,
  health / armor, ammo, CT : T score, round timer, alive counts, kill feed,
  round banner, death and match screens.

Every character (player, bots) plays the UE5 Mannequin's rifle set,
retargeted onto its own skeleton by ``place``; the level's
``BP_MixarGameInfo`` holds per team the mesh, the clips (``ANIMS`` order),
the hand and head bones, the weapon grip transform and the view-model
offset, and the weapon (a ``mixar_role=weapon`` package).

Plain Python (no ``unreal``): asset paths come in as ``assets`` ({name: path},
``game_assets.ensure``). Any change here rebuilds the shooter's Blueprints.
"""

from . import game_spec

FOLDER = "/Game/Mixar/Game"
ACTOR = game_spec.ACTOR
ANIM = game_spec.ANIM
INFO_CLASS = game_spec.GAME_INFO_CLASS
BOT_CLASS = f"{FOLDER}/BP_MixarBot.BP_MixarBot_C"
PLAYER_PARENT = "/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter.BP_ThirdPersonCharacter_C"
CHARACTER = "/Script/Engine.Character"

# The rifle set every character plays, in the order the Blueprints index it.
RIFLE = "/Game/Characters/Mannequins/Anims/Rifle"
DEATH = "/Game/Characters/Mannequins/Anims/Death"
ANIMS = (
    f"{RIFLE}/MF_Rifle_Idle_ADS",              # 0 idle, aiming
    f"{RIFLE}/Walk/MF_Rifle_Walk_Fwd",         # 1
    f"{RIFLE}/Jog/MF_Rifle_Jog_Fwd",           # 2
    f"{RIFLE}/Jog/MF_Rifle_Jog_Bwd",           # 3
    f"{RIFLE}/Jog/MF_Rifle_Jog_Left",          # 4
    f"{RIFLE}/Jog/MF_Rifle_Jog_Right",         # 5
    f"{RIFLE}/MM_Rifle_Fire",                  # 6
    f"{RIFLE}/MM_Rifle_Reload",                # 7
    f"{RIFLE}/HitReact/MM_HitReact_Front_Med_01",  # 8
    f"{DEATH}/MM_Death_Front_01",              # 9
    f"{DEATH}/MM_Death_Back_01",               # 10
    f"{DEATH}/MM_Death_Front_02",              # 11
    f"{RIFLE}/Walk/MF_Rifle_Walk_Bwd",         # 12
    f"{RIFLE}/Walk/MF_Rifle_Walk_Left",        # 13
    f"{RIFLE}/Walk/MF_Rifle_Walk_Right",       # 14
    f"{RIFLE}/Jump/MM_Rifle_Jump_Fall_Loop",   # 15
)

# GameInfo additions the shooter reads (one level, two teams).
INFO_VARIABLES = [
    ("RoundsToWin", "int"), ("BotsPerTeam", "int"), ("RoundSeconds", "float"), ("PlayerTeam", "string"),
    ("CTHand", "name"), ("THand", "name"), ("CTHead", "name"), ("THead", "name"),
    ("CTLeftHand", "name"), ("TLeftHand", "name"), ("ViewEye", "Vector"), ("WeaponReach", "float"),
    ("CTHide", "name", "ARRAY"),
]
INFO_OBJECTS = [
    ("CTMesh", "/Script/Engine.SkeletalMesh", None), ("TMesh", "/Script/Engine.SkeletalMesh", None),
    ("Weapon", "/Script/Engine.StaticMesh", None),
    ("CTAnims", ANIM, "ARRAY"), ("TAnims", ANIM, "ARRAY"),
]
INFO_DEFAULTS = {"RoundsToWin": 5, "BotsPerTeam": 5, "RoundSeconds": 115.0, "PlayerTeam": "ct",
                 "WeaponReach": 60.0}
# Where the first-person eyes sit relative to the camera (camera space, cm:
# X forward, Y right, Z up), so the rifle shows lower right; the level's
# GameInfo ViewEye overrides it (game.py sets it on the CDO).
VIEW_EYE = (3.0, 14.0, -12.0)

# The rifle in a character's hands, measured from the live pose: the grip in
# the right palm, the barrel toward the left hand, the top up. Shared by the
# bot and the player (each has a copy: a function per Blueprint).
_GRIP_FN = """
(fn MixarHold (Body Gun Hand LeftHand Forward)
  ; the barrel along the aim, turned a little toward the supporting hand
  (bind hr (Transformation|GetSocketTransform :self Body :InSocketName Hand :TransformSpace "RTS_World"))
  (bind support (Math|Vector|Normalize (- (Transformation|GetSocketLocation :self Body :InSocketName LeftHand)
                                          (.location hr))))
  (bind barrel (+ (* (Math|Vector|Normalize Forward) 3.0) support))
  (bind aim (Math|Rotator|MakeRotfromYZ :Y barrel :Z (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 1.0)))
  (bind palm (+ (.location hr) (* (Math|Vector|Normalize barrel) 5.0)))
  (bind held (Math|Transform|MakeTransform :Location palm :Rotation aim
                :Scale (Math|Vector|MakeVector :X 1.0 :Y 1.0 :Z 1.0)))
  (Transformation|SetRelativeTransform :self Gun :NewTransform (Math|Transform|MakeRelativeTransform held hr)
    :bSweep false :bTeleport true)
  (Rendering|SetVisibility :self Gun :bNewVisibility true :bPropagateToChildren false))
"""
_GRIP_PARAMS = [("Body", "/Script/Engine.SkeletalMeshComponent", True),
                ("Gun", "/Script/Engine.StaticMeshComponent", True), ("Hand", "name", False),
                ("LeftHand", "name", False), ("Forward", "Vector", False)]

_INFO = (f'(Utilities|Casting|CastToBP_MixarGameInfo '
         f':Object (Actor|GetActorOfClass :ActorClass "{INFO_CLASS}"))')
_GM = "(Utilities|Casting|CastToBP_MixarShooterGameMode :Object (Game|GetGameMode))"


def _a(assets: dict, name: str) -> str:
    return assets.get(name, "")


def _sound2d(assets, name, volume=1.0) -> str:
    path = _a(assets, name)
    return (f'(Audio|PlaySound2D :Sound "{path}" :VolumeMultiplier {volume})' if path
            else '(Development|PrintString :InString "no sound" :bPrintToScreen false)')


def _sound3d(assets, name, where, volume=1.0) -> str:
    path, att = _a(assets, name), _a(assets, "SA_MixarWorld")
    if not path:
        return '(Development|PrintString :InString "no sound" :bPrintToScreen false)'
    extra = f' :AttenuationSettings "{att}"' if att else ""
    return f'(Audio|PlaySoundatLocation :Sound "{path}" :Location {where} :VolumeMultiplier {volume}{extra})'


def _fx(assets, name, where, scale) -> str:
    path = _a(assets, name)
    if not path:
        return '(Development|PrintString :InString "no effect" :bPrintToScreen false)'
    return (f'(Niagara|SpawnSystematLocation :SystemTemplate "{path}" :Location {where} '
            f':Scale (Math|Vector|MakeVector :X {scale} :Y {scale} :Z {scale}))')


def bot(assets: dict) -> dict:
    """BP_MixarBot: one team bot."""
    return {
        "name": "BP_MixarBot",
        "parent": CHARACTER,
        "variables": [
            ("Team", "string"), ("BotName", "string"), ("Health", "float"), ("Armor", "float"), ("Dead", "bool"),
            ("Clock", "float"), ("ThinkAt", "float"), ("ShotAt", "float"), ("ReactAt", "float"), ("Burst", "int"),
            ("HitUntil", "float"), ("StepAt", "float"), ("AnimState", "int"), ("Goal", "Vector"),
            ("HasGoal", "bool"), ("HandBone", "name"), ("HeadBone", "name"), ("Engaged", "bool"),
            ("LeftHand", "name"), ("Calibrated", "bool"), ("Frames", "int"), ("SightedAt", "float"),
        ],
        "object_variables": [("Target", ACTOR, None), ("Anims", ANIM, "ARRAY")],
        "components": [("Gun", "StaticMeshComponent")],
        "functions": [
            ("MixarSetup", [("InTeam", "string", False), ("InName", "string", False)], [], f"""
(fn MixarSetup (InTeam InName)
  (Variables|Default|SetTeam InTeam)
  (Variables|Default|SetBotName InName)
  (Variables|Default|SetHealth 100.0)
  (Variables|Default|SetArmor 100.0)
  (Variables|Default|SetDead false)
  (Variables|Default|SetBurst 3)
  (Variables|Default|SetAnimState -1)
  ; shots and sight lines are Visibility traces: the body stops them (a Pawn ignores the channel)
  (Collision|SetCollisionResponsetoChannel :self (Variables|Character|GetCapsuleComponent)
    :Channel "ECC_Visibility" :NewResponse "ECR_Block")
  (Variables|Default|SetCalibrated false)
  (Variables|Default|SetFrames 0)
  (Rendering|SetVisibility :self (Variables|Default|GetGun) :bNewVisibility false :bPropagateToChildren false)
  (bind body (Variables|Character|GetMesh))
  (bind gun (Variables|Default|GetGun))
  ; the rifle sits at the cheek: a shot that meets it is not a headshot, so it stops nothing
  (Collision|SetCollisionEnabled :self gun :NewType "NoCollision")
  (Class|CharacterMovementComponent|SetOrientRotationtoMovement
    :self (Variables|Character|GetCharacterMovement) :bOrientRotationToMovement true)
  (Class|CharacterMovementComponent|SetMaxWalkSpeed :self (Variables|Character|GetCharacterMovement)
    :MaxWalkSpeed 360.0)
  (Transformation|SetRelativeLocationAndRotation :self body
    :NewLocation (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z -90.0)
    :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw -90.0) :bSweep false :bTeleport true)
  (bind info {_INFO}
    (:then
      (Components|StaticMesh|SetStaticMesh :self gun :NewMesh (Class|BPMixarGameInfo|GetWeapon :self info))
      (if (Utilities|String|EqualExactly(String) InTeam "ct")
        (Components|SkeletalMesh|SetSkeletalMeshAsset :self body :NewMesh (Class|BPMixarGameInfo|GetCTMesh :self info))
        (Variables|Default|SetAnims (Class|BPMixarGameInfo|GetCTAnims :self info))
        (Variables|Default|SetHandBone (Class|BPMixarGameInfo|GetCTHand :self info))
        (Variables|Default|SetHeadBone (Class|BPMixarGameInfo|GetCTHead :self info))
        (Variables|Default|SetLeftHand (Class|BPMixarGameInfo|GetCTLeftHand :self info))
        (Transformation|AttachComponentToComponent :self gun :Parent body
          :SocketName (Class|BPMixarGameInfo|GetCTHand :self info)
          :LocationRule "SnapToTarget" :RotationRule "SnapToTarget" :ScaleRule "KeepWorld" :bWeldSimulatedBodies false)
        (else
          (Components|SkeletalMesh|SetSkeletalMeshAsset :self body :NewMesh (Class|BPMixarGameInfo|GetTMesh :self info))
          (Variables|Default|SetAnims (Class|BPMixarGameInfo|GetTAnims :self info))
          (Variables|Default|SetHandBone (Class|BPMixarGameInfo|GetTHand :self info))
          (Variables|Default|SetHeadBone (Class|BPMixarGameInfo|GetTHead :self info))
          (Variables|Default|SetLeftHand (Class|BPMixarGameInfo|GetTLeftHand :self info))
          (Transformation|AttachComponentToComponent :self gun :Parent body
            :SocketName (Class|BPMixarGameInfo|GetTHand :self info)
            :LocationRule "SnapToTarget" :RotationRule "SnapToTarget" :ScaleRule "KeepWorld" :bWeldSimulatedBodies false))))
    (:CastFailed)))
"""),
            ("MixarPlay", [("Index", "int", False), ("Loop", "bool", False)], [], """
(fn MixarPlay (Index Loop)
  (bind anims (Variables|Default|GetAnims))
  (if (< Index (Utilities|Array|Length anims))
    (Components|Animation|PlayAnimation :self (Variables|Character|GetMesh)
      :NewAnimToPlay (Utilities|Array|Get(acopy) anims Index) :bLooping Loop)))
"""),
            ("MixarTakeDamage", [("Amount", "float", False), ("Headshot", "bool", False), ("From", ACTOR, True)],
             [], """
(fn MixarTakeDamage (Amount Headshot From)
  (if (not (Variables|Default|GetDead))
    (bind hit (* Amount (select Headshot 4.0 1.0)))
    (bind armored (> (Variables|Default|GetArmor) 0.0))
    (Variables|Default|SetHealth (- (Variables|Default|GetHealth) (* hit (select armored 0.775 1.0))))
    (Variables|Default|SetArmor (Math|Float|Max(Float) 0.0 (- (Variables|Default|GetArmor) (* hit 0.2))))
    (Variables|Default|SetHitUntil (+ (Variables|Default|GetClock) 0.35))
    (if (not (Variables|Default|GetEngaged))
      (Variables|Default|SetTarget From)
      (Variables|Default|SetReactAt (+ (Variables|Default|GetClock) 0.2)))
    (if (<= (Variables|Default|GetHealth) 0.0)
      (CallFunction|MixarDie :From From :Headshot Headshot))))
"""),
            ("MixarDie", [("From", ACTOR, True), ("Headshot", "bool", False)], [], f"""
(fn MixarDie (From Headshot)
  (Variables|Default|SetDead true)
  (Variables|Default|SetEngaged false)
  (CallFunction|MixarStopAI)
  (Collision|SetCollisionEnabled :self (Variables|Character|GetCapsuleComponent) :NewType "NoCollision")
  (CallFunction|MixarPlay :Index (Math|Random|RandomIntegerinRange :Min 9 :Max 11) :Loop false)
  (bind gm {_GM}
    (:then
      (Class|BPMixarShooterGameMode|MixarKilled :self gm :Victim self :Killer From :Headshot Headshot))
    (:CastFailed)))
"""),
            ("MixarHold", _GRIP_PARAMS, [], _GRIP_FN),
            ("MixarStopAI", [], [], """
(fn MixarStopAI ()
  (bind ai (Utilities|Casting|CastToAIController :Object (Pawn|GetController :self self))
    (:then
      (AI|Navigation|StopMovement :self ai))
    (:CastFailed)))
"""),
            ("MixarShoot", [], [], f"""
(fn MixarShoot ()
  (bind target (Variables|Default|GetTarget))
  (bind gun (Variables|Default|GetGun))
  (bind eye (+ (Transformation|GetActorLocation :self self) (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 60.0)))
  (bind aimz (select (< (Math|Random|RandomFloat) 0.2) 72.0 30.0))
  (bind aim (+ (Transformation|GetActorLocation :self target) (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z aimz)))
  ; spread like a rifle sprayed by a person: a first shot is accurate, the burst and moving widen it
  (bind moving (> (Math|Vector|VectorLengthXY (Transformation|GetVelocity :self self)) 60.0))
  ; the aim settles on a target it has just seen: wide at first, about a second to tighten
  (bind settle (Math|Float|Max(Float) 0.0 (- 6.0 (* 4.5 (- (Variables|Default|GetClock) (Variables|Default|GetSightedAt))))))
  (bind cone (+ (+ (+ 1.0 settle) (select moving 3.5 0.0))
                (* (- 5 (Math|Integer|Min(Integer) (Variables|Default|GetBurst) 5)) 0.6)))
  (bind dir (Math|Random|RandomUnitVectorinConeinDegrees :ConeDir (Math|Vector|Normalize (- aim eye))
                                                          :ConeHalfAngleInDegrees cone))
  (bind muzzle (+ (Transformation|GetWorldLocation :self gun) (* (Transformation|GetRightVector :self gun) 55.0)))
  {_sound3d(assets, "S_MixarGunshot", "muzzle", 0.9)}
  {_fx(assets, "NS_MixarFlash", "muzzle", 0.045)}
  (bind (hit didHit) (Collision|LineTraceByChannel :Start (+ eye (* dir 60.0)) :End (+ eye (* dir 8000.0))
                        :TraceChannel "Visibility" :bTraceComplex false :bIgnoreSelf true :DrawDebugType "None"))
  (if didHit
    (bind (blocking initial time dist loc impact normal inormal mat actor comp hitbone bone item elem face start end)
          (Collision|BreakHitResult hit))
    (bind gm {_GM}
      (:then
        (if (Class|BPMixarShooterGameMode|MixarIsCombatant :self gm :Who actor)
          (bind head (> (.z impact) (+ (.z (Transformation|GetActorLocation :self actor)) 65.0)))
          {_fx(assets, "NS_MixarBlood", "impact", 0.12)}
          (Class|BPMixarShooterGameMode|MixarDamage :self gm :Victim actor :Amount 27.0 :Headshot head :From self)
          (else
            {_fx(assets, "NS_MixarSparks", "impact", 0.08)})))
      (:CastFailed))))
"""),
            ("MixarThink", [], [], f"""
(fn MixarThink ()
  (bind gm {_GM}
    (:then
      (bind (found any) (Class|BPMixarShooterGameMode|MixarFindTarget :self gm :Seeker self
                                                                       :Team (Variables|Default|GetTeam)))
      (bind ai (Utilities|Casting|CastToAIController :Object (Pawn|GetController :self self))
        (:then
          (if any
              (if (not (Variables|Default|GetEngaged))
                (Variables|Default|SetSightedAt (Variables|Default|GetClock))
                (Variables|Default|SetReactAt (+ (Variables|Default|GetClock)
                                                  (Math|Random|RandomFloatinRange :Min 0.25 :Max 0.6))))
              (Variables|Default|SetEngaged true)
              (Variables|Default|SetTarget found)
              (AI|Navigation|StopMovement :self ai)
              (bind look (Math|Rotator|FindLookatRotation :Start (Transformation|GetActorLocation :self self)
                                                         :Target (Transformation|GetActorLocation :self found)))
              (Transformation|SetActorRotation :self self
                :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw (.yaw look)) :bTeleportPhysics true)
            (else
              (Variables|Default|SetEngaged false)
              (bind here (Transformation|GetActorLocation :self self))
              (if (or (not (Variables|Default|GetHasGoal))
                      (< (Math|Vector|Distance(Vector) here (Variables|Default|GetGoal)) 250.0))
                (Variables|Default|SetGoal (Class|BPMixarShooterGameMode|MixarPatrolPoint :self gm
                                             :Team (Variables|Default|GetTeam)))
                (Variables|Default|SetHasGoal true))
              (AI|Navigation|MovetoLocation :self ai :Dest (Variables|Default|GetGoal) :AcceptanceRadius 120.0
                :bStopOnOverlap true :bUsePathfinding true :bProjectDestinationToNavigation true
                :bCanStrafe false :bAllowPartialPath true))))
        (:CastFailed)))
    (:CastFailed)))
"""),
            ("MixarAnimate", [("Speed", "float", False)], [], f"""
(fn MixarAnimate (Speed)
  (bind want (select (> (Variables|Default|GetHitUntil) (Variables|Default|GetClock)) 8
               (select (Variables|Default|GetEngaged) 0 (select (> Speed 60.0) 2 0))))
  (if (!= want (Variables|Default|GetAnimState))
    (Variables|Default|SetAnimState want)
    (CallFunction|MixarPlay :Index want :Loop (!= want 8)))
  (if (and (> Speed 120.0) (> (Variables|Default|GetClock) (Variables|Default|GetStepAt)))
    (Variables|Default|SetStepAt (+ (Variables|Default|GetClock) 0.34))
    {_sound3d(assets, "S_MixarFootstep", "(Transformation|GetActorLocation :self self)", 0.6)}))
"""),
        ],
        "events": """
(event EventTick (DeltaSeconds)
  (Variables|Default|SetClock (+ (Variables|Default|GetClock) DeltaSeconds))
  ; measured once the aim pose has played a few frames (at spawn the hands are at rest)
  (Variables|Default|SetFrames (+ (Variables|Default|GetFrames) 1))
  ; re-measured every frame: the hand turns between clips, the rifle keeps pointing where the bot faces
  (if (and (> (Variables|Default|GetClock) 0.4) (> (Variables|Default|GetFrames) 5))
    (Variables|Default|SetCalibrated true)
    (CallFunction|MixarHold :Body (Variables|Character|GetMesh) :Gun (Variables|Default|GetGun)
      :Hand (Variables|Default|GetHandBone) :LeftHand (Variables|Default|GetLeftHand)
      :Forward (Transformation|GetActorForwardVector :self self)))
  (if (not (Variables|Default|GetDead))
    (if (> (Variables|Default|GetClock) (Variables|Default|GetThinkAt))
      (Variables|Default|SetThinkAt (+ (Variables|Default|GetClock) 0.2))
      (CallFunction|MixarThink))
    (if (and (Variables|Default|GetEngaged)
             (and (> (Variables|Default|GetClock) (Variables|Default|GetReactAt))
                  (> (Variables|Default|GetClock) (Variables|Default|GetShotAt))))
      (Utilities|IsValid (Variables|Default|GetTarget)
        (:"Is Valid"
          (CallFunction|MixarShoot)
          (Variables|Default|SetBurst (- (Variables|Default|GetBurst) 1))
          (if (> (Variables|Default|GetBurst) 0)
            (Variables|Default|SetShotAt (+ (Variables|Default|GetClock) 0.1))
            (else
              (Variables|Default|SetShotAt (+ (Variables|Default|GetClock)
                                             (Math|Random|RandomFloatinRange :Min 0.35 :Max 0.8)))
              (Variables|Default|SetBurst (Math|Random|RandomIntegerinRange :Min 3 :Max 6)))))
        (:"Is Not Valid"
          (Variables|Default|SetEngaged false))))
    (CallFunction|MixarAnimate :Speed (Math|Vector|VectorLengthXY (Transformation|GetVelocity :self self)))))
""",
    }


def player(assets: dict) -> dict:
    """BP_MixarShooterPlayer: the first-person player."""
    return {
        "name": "BP_MixarShooterPlayer",
        "parent": PLAYER_PARENT,
        "variables": [
            ("Team", "string"), ("Health", "float"), ("Armor", "float"), ("Ammo", "int"), ("Reserve", "int"),
            ("Dead", "bool"), ("FireHeld", "bool"), ("ReloadHeld", "bool"), ("God", "bool"), ("ShotAt", "float"),
            ("ReloadUntil", "float"), ("Reloading", "bool"), ("Spray", "int"), ("RecoilDebt", "float"),
            ("LastFireAt", "float"), ("Clock", "float"), ("AnimState", "int"), ("StepAt", "float"),
            ("ViewKick", "float"), ("ViewBase", "Vector"), ("Spread", "float"),
            ("HandBone", "name"), ("LeftHand", "name"), ("HeadBone", "name"), ("Calibrated", "bool"),
            ("ViewEye", "Vector"), ("Frames", "int"), ("Moving", "int"), ("Delta", "float"),
        ],
        "editable": True,
        "object_variables": [("Anims", ANIM, "ARRAY")],
        "components": [("View", "SkeletalMeshComponent"), ("Gun1P", "StaticMeshComponent"),
                       ("Gun3P", "StaticMeshComponent")],
        "functions": [
            ("MixarSetupFP", [], [], f"""
(fn MixarSetupFP ()
  (Collision|SetCollisionResponsetoChannel :self (Variables|Character|GetCapsuleComponent)
    :Channel "ECC_Visibility" :NewResponse "ECR_Block")
  (CallFunction|MixarArm :Length 0.0)
  (CallFunction|MixarCam)
  (Variables|Pawn|SetUseControllerRotationYaw true)
  (bind moves (Variables|Character|GetCharacterMovement))
  (Class|CharacterMovementComponent|SetOrientRotationtoMovement :self moves :bOrientRotationToMovement false)
  (bind body (Variables|Character|GetMesh))
  (bind view (Variables|Default|GetView))
  (bind gun1 (Variables|Default|GetGun1P))
  (bind gun3 (Variables|Default|GetGun3P))
  ; the rifles and the view model stop no shot or sight line (only the body does)
  (Collision|SetCollisionEnabled :self gun1 :NewType "NoCollision")
  (Collision|SetCollisionEnabled :self gun3 :NewType "NoCollision")
  (Collision|SetCollisionEnabled :self view :NewType "NoCollision")
  (Rendering|SetOwnerNoSee :self body :bNewOwnerNoSee true)
  (Rendering|SetVisibility :self view :bNewVisibility false :bPropagateToChildren true)
  (Rendering|SetOwnerNoSee :self gun3 :bNewOwnerNoSee true)
  (Rendering|SetOnlyOwnerSee :self view :bNewOnlyOwnerSee true)
  (Rendering|SetOnlyOwnerSee :self gun1 :bNewOnlyOwnerSee true)
  (Rendering|SetCastShadow :self view :NewCastShadow false)
  (Rendering|SetCastShadow :self gun1 :NewCastShadow false)
  (Rendering|SetVisibility :self gun1 :bNewVisibility false :bPropagateToChildren false)
  (Rendering|SetVisibility :self gun3 :bNewVisibility false :bPropagateToChildren false)
  (Variables|Default|SetCalibrated false)
  (Variables|Default|SetFrames 0)
  (Variables|Default|SetClock 0.0)
  (Variables|Default|SetAnimState -1)
  (bind info {_INFO}
    (:then
      (bind weapon (Class|BPMixarGameInfo|GetWeapon :self info))
      (Components|StaticMesh|SetStaticMesh :self gun1 :NewMesh weapon)
      (Components|StaticMesh|SetStaticMesh :self gun3 :NewMesh weapon)
      (Components|SkeletalMesh|SetSkeletalMeshAsset :self body :NewMesh (Class|BPMixarGameInfo|GetCTMesh :self info))
      (Components|SkeletalMesh|SetSkeletalMeshAsset :self view :NewMesh (Class|BPMixarGameInfo|GetCTMesh :self info))
      (Variables|Default|SetAnims (Class|BPMixarGameInfo|GetCTAnims :self info))
      (Variables|Default|SetViewBase (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z -150.0))
      (Variables|Default|SetViewEye (Class|BPMixarGameInfo|GetViewEye :self info))
      (Transformation|SetRelativeLocationAndRotation :self view :NewLocation (Variables|Default|GetViewBase)
        :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw -90.0) :bSweep false :bTeleport true)
      (for bone (Class|BPMixarGameInfo|GetCTHide :self info)
        (Components|SkinnedMesh|HideBonebyName :self view :BoneName bone :PhysBodyOption "PBO_None"))
      (bind hand (Class|BPMixarGameInfo|GetCTHand :self info))
      (Variables|Default|SetHandBone hand)
      (Variables|Default|SetLeftHand (Class|BPMixarGameInfo|GetCTLeftHand :self info))
      (Variables|Default|SetHeadBone (Class|BPMixarGameInfo|GetCTHead :self info))
      (Transformation|AttachComponentToComponent :self gun1 :Parent view :SocketName hand
        :LocationRule "SnapToTarget" :RotationRule "SnapToTarget" :ScaleRule "KeepWorld" :bWeldSimulatedBodies false)
      (Transformation|AttachComponentToComponent :self gun3 :Parent body :SocketName hand
        :LocationRule "SnapToTarget" :RotationRule "SnapToTarget" :ScaleRule "KeepWorld" :bWeldSimulatedBodies false))
    (:CastFailed)))
"""),
            ("MixarHold", _GRIP_PARAMS, [], _GRIP_FN),
            ("MixarCalibrate", [], [], """
(fn MixarCalibrate ()
  ; the rifle into both view and body hands, then the view model so the eyes
  ; sit at ViewEye from the camera (the rifle lower right)
  (bind view (Variables|Default|GetView))
  ; the camera component itself (the camera manager can still be at the origin)
  (bind (where turn) (CallFunction|MixarCameraPose))
  (CallFunction|MixarHold :Body view :Gun (Variables|Default|GetGun1P) :Hand (Variables|Default|GetHandBone)
    :LeftHand (Variables|Default|GetLeftHand) :Forward (Math|Vector|GetForwardVector turn))
  (CallFunction|MixarHold :Body (Variables|Character|GetMesh) :Gun (Variables|Default|GetGun3P)
    :Hand (Variables|Default|GetHandBone) :LeftHand (Variables|Default|GetLeftHand)
    :Forward (Transformation|GetActorForwardVector :self self))
  (bind eyes (Transformation|GetSocketLocation :self view :InSocketName (Variables|Default|GetHeadBone)))
  (bind want (+ where (Math|Vector|RotateVector :A (Variables|Default|GetViewEye) :B turn)))
  (Variables|Default|SetViewBase (+ (Variables|Default|GetViewBase) (Math|Vector|UnrotateVector :A (- want eyes) :B turn)))
  (Rendering|SetVisibility :self view :bNewVisibility true :bPropagateToChildren true))
"""),
            ("MixarCameraPose", [], [("Where", "Vector"), ("Turn", "Rotator")], """
(fn MixarCameraPose ()
  (bind cam (Utilities|Casting|CastToCameraComponent
              :Object (Actor|GetComponentbyClass :self self :ComponentClass "/Script/Engine.CameraComponent"))
    (:then
      (return (Transformation|GetWorldLocation :self cam) (Transformation|GetWorldRotation :self cam)))
    (:CastFailed
      (return (Transformation|GetActorLocation :self self) (Transformation|GetActorRotation :self self)))))
"""),
            ("MixarArm", [("Length", "float", False)], [], """
(fn MixarArm (Length)
  ; the camera boom: 0 = first person at the eyes, longer = a death camera
  (bind arm (Utilities|Casting|CastToSpringArmComponent
              :Object (Actor|GetComponentbyClass :self self :ComponentClass "/Script/Engine.SpringArmComponent"))
    (:then
      (Class|SpringArmComponent|SetTargetArmLength :self arm :TargetArmLength Length)
      (Class|SpringArmComponent|SetSocketOffset :self arm :SocketOffset (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 0.0))
      (Transformation|SetRelativeLocation :self arm :NewLocation (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 64.0)
        :bSweep false :bTeleport true)
      (Class|SpringArmComponent|SetDoCollisionTest :self arm :bDoCollisionTest (> Length 0.0)))
    (:CastFailed)))
"""),
            ("MixarCam", [], [], """
(fn MixarCam ()
  (bind cam (Utilities|Casting|CastToCameraComponent
              :Object (Actor|GetComponentbyClass :self self :ComponentClass "/Script/Engine.CameraComponent"))
    (:then
      (Camera|SetFieldOfView :self cam :InFieldOfView 90.0)
      (Transformation|AttachComponentToComponent :self (Variables|Default|GetView) :Parent cam :SocketName "None"
        :LocationRule "KeepRelative" :RotationRule "KeepRelative" :ScaleRule "KeepRelative" :bWeldSimulatedBodies false))
    (:CastFailed)))
"""),
            ("MixarPlayView", [("Index", "int", False), ("Loop", "bool", False)], [], """
(fn MixarPlayView (Index Loop)
  (bind anims (Variables|Default|GetAnims))
  (if (< Index (Utilities|Array|Length anims))
    (bind clip (Utilities|Array|Get(acopy) anims Index))
    (Components|Animation|PlayAnimation :self (Variables|Default|GetView) :NewAnimToPlay clip :bLooping Loop)
    (Components|Animation|PlayAnimation :self (Variables|Character|GetMesh) :NewAnimToPlay clip :bLooping Loop)))
"""),
            ("MixarRespawn", [("Where", "Vector", False), ("Yaw", "float", False)], [], """
(fn MixarRespawn (Where Yaw)
  (Variables|Default|SetHealth 100.0)
  (Variables|Default|SetArmor 100.0)
  (Variables|Default|SetAmmo 30)
  (Variables|Default|SetReserve 90)
  (Variables|Default|SetReloading false)
  (Variables|Default|SetSpray 0)
  (Variables|Default|SetRecoilDebt 0.0)
  (Variables|Default|SetDead false)
  (Variables|Default|SetAnimState -1)
  (Transformation|SetActorLocation :self self :NewLocation (+ Where (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 95.0))
    :bSweep false :bTeleport true)
  (bind pc (Game|GetPlayerController :PlayerIndex 0))
  (Pawn|SetControlRotation :self pc :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw Yaw))
  (Input|EnableInput :self self :PlayerController pc)
  (Collision|SetCollisionEnabled :self (Variables|Character|GetCapsuleComponent) :NewType "QueryAndPhysics")
  (CallFunction|MixarArm :Length 0.0)
  (Rendering|SetOwnerNoSee :self (Variables|Character|GetMesh) :bNewOwnerNoSee true)
  ; shown once calibrated (before that the arms are not where the eyes are)
  (Rendering|SetVisibility :self (Variables|Default|GetView) :bNewVisibility (Variables|Default|GetCalibrated)
    :bPropagateToChildren true))
"""),
            ("MixarTakeDamage", [("Amount", "float", False), ("Headshot", "bool", False), ("From", ACTOR, True)],
             [], f"""
(fn MixarTakeDamage (Amount Headshot From)
  ; God: a playtest's cheat (as CS's god), so a test of the rifle is not cut short
  (if (and (not (Variables|Default|GetDead)) (not (Variables|Default|GetGod)))
    (bind hit (* Amount (select Headshot 4.0 1.0)))
    (bind armored (> (Variables|Default|GetArmor) 0.0))
    (Variables|Default|SetHealth (Math|Float|Max(Float) 0.0
      (- (Variables|Default|GetHealth) (* hit (select armored 0.775 1.0)))))
    (Variables|Default|SetArmor (Math|Float|Max(Float) 0.0 (- (Variables|Default|GetArmor) (* hit 0.2))))
    {_sound2d(assets, "S_MixarHurt", 0.5)}
    (if (<= (Variables|Default|GetHealth) 0.0)
      (Variables|Default|SetDead true)
      (Variables|Default|SetFireHeld false)
      (bind pc (Game|GetPlayerController :PlayerIndex 0))
      (Input|DisableInput :self self :PlayerController pc)
      (Rendering|SetVisibility :self (Variables|Default|GetView) :bNewVisibility false :bPropagateToChildren true)
      (Rendering|SetOwnerNoSee :self (Variables|Character|GetMesh) :bNewOwnerNoSee false)
      (CallFunction|MixarArm :Length 320.0)
      (CallFunction|MixarPlayView :Index (Math|Random|RandomIntegerinRange :Min 9 :Max 11) :Loop false)
      (Collision|SetCollisionEnabled :self (Variables|Character|GetCapsuleComponent) :NewType "NoCollision")
      (bind gm {_GM}
        (:then
          (Class|BPMixarShooterGameMode|MixarKilled :self gm :Victim self :Killer From :Headshot Headshot))
        (:CastFailed)))))
"""),
            ("MixarShoot", [], [], f"""
(fn MixarShoot ()
  (Variables|Default|SetAmmo (- (Variables|Default|GetAmmo) 1))
  ; the next shot 0.1 s on, counted from the shot due this frame (at most one frame back)
  (Variables|Default|SetShotAt (+ (Math|Float|Max(Float) (Variables|Default|GetShotAt)
                                    (- (Variables|Default|GetClock) (Variables|Default|GetDelta))) 0.1))
  (Variables|Default|SetLastFireAt (Variables|Default|GetClock))
  (Variables|Default|SetSpray (+ (Variables|Default|GetSpray) 1))
  (Variables|Default|SetViewKick 1.0)
  {_sound2d(assets, "S_MixarGunshot", 0.8)}
  (bind gun (Variables|Default|GetGun1P))
  (bind muzzle (+ (Transformation|GetWorldLocation :self gun) (* (Transformation|GetRightVector :self gun) 55.0)))
  {_fx(assets, "NS_MixarFlash", "muzzle", 0.035)}
  (bind cm (Game|GetPlayerCameraManager :PlayerIndex 0))
  (bind start (Camera|GetCameraLocation :self cm))
  (bind facing (Camera|GetCameraRotation :self cm))
  (bind dir (Math|Random|RandomUnitVectorinConeinDegrees :ConeDir (Math|Vector|GetForwardVector facing)
                                                          :ConeHalfAngleInDegrees (Variables|Default|GetSpread)))
  (bind (hit didHit) (Collision|LineTraceByChannel :Start start :End (+ start (* dir 10000.0))
                        :TraceChannel "Visibility" :bTraceComplex false :bIgnoreSelf true :DrawDebugType "None"))
  (if didHit
    (bind (blocking initial time dist loc impact normal inormal mat actor comp hitbone bone item elem face tstart tend)
          (Collision|BreakHitResult hit))
    (bind gm {_GM}
      (:then
        (if (Class|BPMixarShooterGameMode|MixarIsCombatant :self gm :Who actor)
          (bind head (> (.z impact) (+ (.z (Transformation|GetActorLocation :self actor)) 65.0)))
          {_fx(assets, "NS_MixarBlood", "impact", 0.12)}
          (Class|BPMixarShooterGameMode|MixarDamage :self gm :Victim actor :Amount 27.0 :Headshot head :From self)
          (else
            {_fx(assets, "NS_MixarSparks", "impact", 0.08)})))
      (:CastFailed)))
  (bind spray (Math|Integer|Min(Integer) (Variables|Default|GetSpray) 10))
  (bind kick (+ 0.45 (* spray 0.09)))
  (bind jitter (select (> (Variables|Default|GetSpray) 6) (Math|Random|RandomFloatinRange :Min -0.35 :Max 0.35) 0.0))
  (bind pc (Game|GetPlayerController :PlayerIndex 0))
  (bind rot (Pawn|GetControlRotation :self pc))
  (Pawn|SetControlRotation :self pc
    :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch (+ (.pitch rot) kick) :Yaw (+ (.yaw rot) jitter)))
  (Variables|Default|SetRecoilDebt (+ (Variables|Default|GetRecoilDebt) (* kick 0.6))))
"""),
            ("MixarViewAnim", [("Speed", "float", False), ("Forward", "float", False), ("Side", "float", False)],
             [], """
(fn MixarViewAnim (Speed Forward Side)
  (bind run (> Speed 300.0))
  (bind side (> (Math|Float|Absolute(Float) Side) (Math|Float|Absolute(Float) Forward)))
  (bind moving (select (> Forward 0.0) (select run 2 1) (select run 3 12)))
  (bind strafe (select (> Side 0.0) (select run 5 14) (select run 4 13)))
  (bind want (select (< Speed 40.0) 0 (select side strafe moving)))
  (if (and (not (Variables|Default|GetReloading)) (!= want (Variables|Default|GetAnimState)))
    (Variables|Default|SetAnimState want)
    (CallFunction|MixarPlayView :Index want :Loop true)))
"""),
        ],
        "events": f"""
(event EventTick (DeltaSeconds)
  ; set first, then bound to the variable: a bound expression is re-read at each use, so
  ; (bind clock (+ Clock Delta)) read after SetClock would run a frame ahead
  (Variables|Default|SetClock (+ (Variables|Default|GetClock) DeltaSeconds))
  (bind clock (Variables|Default|GetClock))
  (Variables|Default|SetDelta DeltaSeconds)
  (Variables|Default|SetFrames (+ (Variables|Default|GetFrames) 1))
  (if (and (not (Variables|Default|GetCalibrated)) (and (> clock 0.4) (> (Variables|Default|GetFrames) 5)))
    (Variables|Default|SetCalibrated true)
    (CallFunction|MixarCalibrate))
  (if (Variables|Default|GetCalibrated)
    (bind (where turn) (CallFunction|MixarCameraPose))
    (CallFunction|MixarHold :Body (Variables|Default|GetView) :Gun (Variables|Default|GetGun1P)
      :Hand (Variables|Default|GetHandBone) :LeftHand (Variables|Default|GetLeftHand)
      :Forward (Math|Vector|GetForwardVector turn))
    (CallFunction|MixarHold :Body (Variables|Character|GetMesh) :Gun (Variables|Default|GetGun3P)
      :Hand (Variables|Default|GetHandBone) :LeftHand (Variables|Default|GetLeftHand)
      :Forward (Transformation|GetActorForwardVector :self self)))
  (if (not (Variables|Default|GetDead))
    (bind pc (Game|GetPlayerController :PlayerIndex 0))
    (bind fire (or (Variables|Default|GetFireHeld) (Game|Player|IsInputKeyDown :self pc :Key "LeftMouseButton")))
    (bind reloadKey (or (Variables|Default|GetReloadHeld) (Game|Player|IsInputKeyDown :self pc :Key "R")))
    (bind walk (Game|Player|IsInputKeyDown :self pc :Key "LeftShift"))
    (bind moves (Variables|Character|GetCharacterMovement))
    (Class|CharacterMovementComponent|SetMaxWalkSpeed :self moves :MaxWalkSpeed (select walk 230.0 420.0))
    (if (Game|Player|IsInputKeyDown :self pc :Key "LeftControl")
      (Character|Crouch :self self)
      (else
        (Character|UnCrouch :self self)))
    (bind velocity (Transformation|GetVelocity :self self))
    (bind speed (Math|Vector|VectorLengthXY velocity))
    (bind airborne (Movement|IsFalling :self moves))
    (Variables|Default|SetSpread (+ (+ 0.2 (* (Math|Integer|Min(Integer) (Variables|Default|GetSpray) 10) 0.12))
                                    (select airborne 6.0 (select (> speed 250.0) 2.5 (select (> speed 60.0) 0.8 0.0)))))
    (if (and (Variables|Default|GetReloading) (>= clock (Variables|Default|GetReloadUntil)))
      ; kept in a variable: a bound expression is re-read at each use, after SetAmmo it would be 0
      (Variables|Default|SetMoving (Math|Integer|Min(Integer) (- 30 (Variables|Default|GetAmmo))
                                                             (Variables|Default|GetReserve)))
      (Variables|Default|SetAmmo (+ (Variables|Default|GetAmmo) (Variables|Default|GetMoving)))
      (Variables|Default|SetReserve (- (Variables|Default|GetReserve) (Variables|Default|GetMoving)))
      (Variables|Default|SetReloading false)
      (Variables|Default|SetAnimState -1))
    (if (and (not (Variables|Default|GetReloading))
             (and (or reloadKey (and fire (== (Variables|Default|GetAmmo) 0)))
                  (and (< (Variables|Default|GetAmmo) 30) (> (Variables|Default|GetReserve) 0))))
      (Variables|Default|SetReloading true)
      (Variables|Default|SetReloadHeld false)
      (Variables|Default|SetReloadUntil (+ clock 2.4))
      (Variables|Default|SetAnimState 7)
      (CallFunction|MixarPlayView :Index 7 :Loop false)
      {_sound2d(assets, "S_MixarReload", 0.7)})
    ; every shot due since the last frame, so the rate holds at any frame rate
    (while (and fire (and (not (Variables|Default|GetReloading))
                          (and (>= clock (Variables|Default|GetShotAt)) (> (Variables|Default|GetAmmo) 0))))
      (CallFunction|MixarShoot))
    (if (and fire (and (not (Variables|Default|GetReloading)) (>= clock (Variables|Default|GetShotAt))))
      (if (== (Variables|Default|GetAmmo) 0)
        (Variables|Default|SetShotAt (+ clock 0.25))
        {_sound2d(assets, "S_MixarDryfire", 0.6)}))
    (if (and (not fire) (> clock (+ (Variables|Default|GetLastFireAt) 0.3)))
      (Variables|Default|SetSpray 0))
    (if (and (not fire) (> (Variables|Default|GetRecoilDebt) 0.0))
      (bind step (Math|Float|Min(Float) (Variables|Default|GetRecoilDebt) (* DeltaSeconds 9.0)))
      (Variables|Default|SetRecoilDebt (- (Variables|Default|GetRecoilDebt) step))
      (bind rot (Pawn|GetControlRotation :self pc))
      (Pawn|SetControlRotation :self pc
        :NewRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch (- (.pitch rot) step) :Yaw (.yaw rot))))
    (Variables|Default|SetViewKick (Math|Float|Max(Float) 0.0 (- (Variables|Default|GetViewKick) (* DeltaSeconds 9.0))))
    (bind kick (Variables|Default|GetViewKick))
    (Transformation|SetRelativeLocation :self (Variables|Default|GetView)
      :NewLocation (+ (Variables|Default|GetViewBase) (Math|Vector|MakeVector :X (* kick -3.5) :Y 0.0 :Z (* kick 0.6)))
      :bSweep false :bTeleport true)
    (bind facing (Transformation|GetActorRotation :self self))
    (CallFunction|MixarViewAnim :Speed speed
      :Forward (Math|Vector|DotProduct velocity (Math|Vector|GetForwardVector facing))
      :Side (Math|Vector|DotProduct velocity (Math|Vector|GetRightVector facing)))
    (if (and (and (> speed 300.0) (not airborne)) (> clock (Variables|Default|GetStepAt)))
      (Variables|Default|SetStepAt (+ clock 0.36))
      {_sound2d(assets, "S_MixarFootstep", 0.35)})))
""",
    }


def game_mode(assets: dict) -> dict:
    """BP_MixarShooterGameMode: rounds, teams, the kill feed."""
    return {
        "name": "BP_MixarShooterGameMode",
        "parent": f"{FOLDER}/BP_MixarGameMode.BP_MixarGameMode_C",
        "variables": [
            ("ScoreCT", "int"), ("ScoreT", "int"), ("RoundNo", "int"), ("RoundLeft", "float"), ("RoundOver", "bool"),
            ("NextRoundAt", "float"), ("Kills", "int"), ("Banner", "string"), ("BannerUntil", "float"), ("FreezeUntil", "float"),
            ("Feed", "string", "ARRAY"), ("FeedAt", "float", "ARRAY"), ("MatchOver", "bool"),
            ("LastHitAt", "float"), ("LastHeadshotAt", "float"), ("AliveCT", "int"), ("AliveT", "int"),
            ("ReportAt", "float"), ("Range", "float"), ("HasBest", "bool"), ("Tally", "int"),
        ],
        "object_variables": [("Info", ACTOR, None), ("Bots", ACTOR, "ARRAY"), ("CTSpawns", ACTOR, "ARRAY"),
                             ("TSpawns", ACTOR, "ARRAY"), ("Shooter", CHARACTER, None), ("Best", ACTOR, None)],
        "functions": [
            ("MixarIsCombatant", [("Who", ACTOR, True)], [("Result", "bool")], """
(fn MixarIsCombatant (Who)
  (return (or (Utilities|Array|ContainsItem (Variables|Default|GetBots) Who)
              (== Who (Variables|Default|GetShooter)))))
"""),
            ("MixarTeamOf", [("Who", ACTOR, True)], [("Team", "string")], """
(fn MixarTeamOf (Who)
  (bind bot (Utilities|Casting|CastToBP_MixarBot :Object Who)
    (:then
      (return (Class|BPMixarBot|GetTeam :self bot)))
    (:CastFailed
      (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object Who)
        (:then
          (return (Class|BPMixarShooterPlayer|GetTeam :self me)))
        (:CastFailed
          (return ""))))))
"""),
            ("MixarAlive", [("Who", ACTOR, True)], [("Result", "bool")], """
(fn MixarAlive (Who)
  (bind bot (Utilities|Casting|CastToBP_MixarBot :Object Who)
    (:then
      (return (not (Class|BPMixarBot|GetDead :self bot))))
    (:CastFailed
      (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object Who)
        (:then
          (return (not (Class|BPMixarShooterPlayer|GetDead :self me))))
        (:CastFailed
          (return false))))))
"""),
            ("MixarConsider", [("Seeker", ACTOR, True), ("Who", ACTOR, True), ("Team", "string", False),
                               ("Eye", "Vector", False)], [], """
(fn MixarConsider (Seeker Who Team Eye)
  ; Who becomes Best when it is an enemy, alive, nearer than Range and in sight
  (if (and (!= Who Seeker)
           (and (CallFunction|MixarAlive :Who Who)
                (not (Utilities|String|EqualExactly(String) (CallFunction|MixarTeamOf :Who Who) Team))))
    (bind there (+ (Transformation|GetActorLocation :self Who) (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 40.0)))
    (bind dist (Math|Vector|Distance(Vector) Eye there))
    (bind facing (Math|Vector|DotProduct (Transformation|GetActorForwardVector :self Seeker)
                                         (Math|Vector|Normalize (- there Eye))))
    ; seen when in front (a field of view near 150 degrees) or close enough to hear
    (if (and (< dist (Variables|Default|GetRange)) (or (> facing 0.25) (< dist 700.0)))
      ; from just outside the seeker's capsule (it blocks Visibility; this trace is the GameMode's, not its own)
      (bind (hit didHit) (Collision|LineTraceByChannel :Start (+ Eye (* (Math|Vector|Normalize (- there Eye)) 60.0)) :End there :TraceChannel "Visibility"
                            :bTraceComplex false :bIgnoreSelf true :DrawDebugType "None"))
      (bind (blocking initial time d loc impact normal inormal mat actor comp hitbone bone item elem face s e)
            (Collision|BreakHitResult hit))
      (if (or (not didHit) (== actor Who))
        (Variables|Default|SetRange dist)
        (Variables|Default|SetBest Who)
        (Variables|Default|SetHasBest true)))))
"""),
            ("MixarFindTarget", [("Seeker", ACTOR, True), ("Team", "string", False)],
             [("Found", ACTOR), ("Any", "bool")], """
(fn MixarFindTarget (Seeker Team)
  (if (< (Variables|Default|GetClock) (Variables|Default|GetFreezeUntil))
    (return Seeker false))
  (bind eye (+ (Transformation|GetActorLocation :self Seeker) (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 60.0)))
  (Variables|Default|SetRange 4500.0)
  (Variables|Default|SetHasBest false)
  (for who (Variables|Default|GetBots)
    (CallFunction|MixarConsider :Seeker Seeker :Who who :Team Team :Eye eye))
  (CallFunction|MixarConsider :Seeker Seeker :Who (Variables|Default|GetShooter) :Team Team :Eye eye)
  (return (Variables|Default|GetBest) (Variables|Default|GetHasBest)))
"""),
            ("MixarDamage", [("Victim", ACTOR, True), ("Amount", "float", False), ("Headshot", "bool", False),
                             ("From", ACTOR, True)], [], f"""
(fn MixarDamage (Victim Amount Headshot From)
  (if (and (CallFunction|MixarAlive :Who Victim)
           (not (Utilities|String|EqualExactly(String) (CallFunction|MixarTeamOf :Who Victim)
                                                     (CallFunction|MixarTeamOf :Who From))))
    (if (== From (Variables|Default|GetShooter))
      (Variables|Default|SetLastHitAt (Variables|Default|GetClock))
      (if Headshot
        (Variables|Default|SetLastHeadshotAt (Variables|Default|GetClock))
        {_sound2d(assets, "S_MixarHeadshot", 0.6)}
        (else
          {_sound2d(assets, "S_MixarHitmarker", 0.5)})))
    (if (== Victim (Variables|Default|GetShooter))
      (Variables|Default|SetLastHurt (Variables|Default|GetClock)))
    (bind bot (Utilities|Casting|CastToBP_MixarBot :Object Victim)
      (:then
        (Class|BPMixarBot|MixarTakeDamage :self bot :Amount Amount :Headshot Headshot :From From))
      (:CastFailed
        (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object Victim)
          (:then
            (Class|BPMixarShooterPlayer|MixarTakeDamage :self me :Amount Amount :Headshot Headshot :From From))
          (:CastFailed))))))
"""),
            ("MixarNameOf", [("Who", ACTOR, True)], [("Name", "string")], """
(fn MixarNameOf (Who)
  (bind bot (Utilities|Casting|CastToBP_MixarBot :Object Who)
    (:then
      (return (Class|BPMixarBot|GetBotName :self bot)))
    (:CastFailed
      (return "You"))))
"""),
            ("MixarKilled", [("Victim", ACTOR, True), ("Killer", ACTOR, True), ("Headshot", "bool", False)], [],
             """
(fn MixarKilled (Victim Killer Headshot)
  (bind line (Utilities|String|Append (Utilities|String|Append (CallFunction|MixarNameOf :Who Killer) "   >   ")
               (CallFunction|MixarNameOf :Who Victim)))
  (Utilities|Array|Add (Variables|Default|GetFeed) (select Headshot (Utilities|String|Append line "   (HS)") line))
  (Utilities|Array|Add (Variables|Default|GetFeedAt) (Variables|Default|GetClock))
  (if (== Killer (Variables|Default|GetShooter))
    (Variables|Default|SetKills (+ (Variables|Default|GetKills) 1)))
  (if (== Victim (Variables|Default|GetShooter))
    (Variables|Default|SetDeaths (+ (Variables|Default|GetDeaths) 1))))
"""),
            ("MixarSpawnCenter", [("Team", "string", False)], [("Where", "Vector")], """
(fn MixarSpawnCenter (Team)
  (bind spots (select (Utilities|String|EqualExactly(String) Team "ct") (Variables|Default|GetCTSpawns)
                (Variables|Default|GetTSpawns)))
  (if (> (Utilities|Array|Length spots) 0)
    (return (Transformation|GetActorLocation :self (Utilities|Array|Get(acopy) spots 0)))
    (else
      (return (Transformation|GetActorLocation :self (Variables|Default|GetShooter))))))
"""),
            ("MixarPatrolPoint", [("Team", "string", False)], [("Where", "Vector")], """
(fn MixarPatrolPoint (Team)
  (bind enemy (CallFunction|MixarSpawnCenter :Team (select (Utilities|String|EqualExactly(String) Team "ct") "t" "ct")))
  (bind home (CallFunction|MixarSpawnCenter :Team Team))
  (bind middle (* (+ enemy home) 0.5))
  (bind toward (select (< (Math|Random|RandomFloat) 0.6) enemy middle))
  (return (+ toward (Math|Vector|MakeVector :X (Math|Random|RandomFloatinRange :Min -900.0 :Max 900.0)
                                            :Y (Math|Random|RandomFloatinRange :Min -900.0 :Max 900.0) :Z 0.0))))
"""),
            ("MixarSpawnTeam", [("Team", "string", False), ("Count", "int", False), ("First", "int", False)], [],
             f"""
(fn MixarSpawnTeam (Team Count First)
  (bind home (CallFunction|MixarSpawnCenter :Team Team))
  (bind enemy (CallFunction|MixarSpawnCenter :Team (select (Utilities|String|EqualExactly(String) Team "ct") "t" "ct")))
  (bind facing (Math|Rotator|FindLookatRotation :Start home :Target enemy))
  (bind spots (select (Utilities|String|EqualExactly(String) Team "ct") (Variables|Default|GetCTSpawns)
                (Variables|Default|GetTSpawns)))
  (bind n (Math|Integer|Max(Integer) (Utilities|Array|Length spots) 1))
  (for i (range Count)
    (bind slot (+ i First))
    (bind base (select (> (Utilities|Array|Length spots) 0)
                 (Transformation|GetActorLocation :self (Utilities|Array|Get(acopy) spots (Math|Integer|%(Integer) slot n))) home))
    ; one per spawn point, then lined up behind it (away from the enemy), 1.5 m apart: slot 0 is the player's
    (bind row (/ slot n))
    (bind back (Math|Vector|Normalize (Math|Vector|MakeVector :X (- (.x home) (.x enemy)) :Y (- (.y home) (.y enemy)) :Z 0.0)))
    (bind at (+ (+ base (* back (* row 150.0)))
                (Math|Vector|MakeVector :X 0.0 :Y 0.0 :Z 100.0)))
    (bind spawned (Game|SpawnActorfromClass :Class "{BOT_CLASS}"
                    :SpawnTransform (Math|Transform|MakeTransform :Location at
                                      :Rotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0 :Yaw (.yaw facing)))
                    :CollisionHandlingOverride "AdjustIfPossibleButAlwaysSpawn"))
    (bind bot (Utilities|Casting|CastToBP_MixarBot :Object spawned)
      (:then
        (Class|BPMixarBot|MixarSetup :self bot :InTeam Team
          :InName (Utilities|String|Append (select (Utilities|String|EqualExactly(String) Team "ct") "CT " "T ")
                    (Utilities|String|ToString(Integer) (+ i 1))))
        (Utilities|Array|Add (Variables|Default|GetBots) bot))
      (:CastFailed))))
"""),
            ("MixarStartRound", [], [], f"""
(fn MixarStartRound ()
  (for old (Variables|Default|GetBots)
    (Actor|DestroyActor :self old))
  (Utilities|Array|Clear (Variables|Default|GetBots))
  (Variables|Default|SetRoundNo (+ (Variables|Default|GetRoundNo) 1))
  (Variables|Default|SetRoundOver false)
  (Variables|Default|SetBanner (Utilities|String|Append "Round " (Utilities|String|ToString(Integer)
                                                                   (Variables|Default|GetRoundNo))))
  (Variables|Default|SetBannerUntil (+ (Variables|Default|GetClock) 2.0))
  ; freeze time, as in CS: the teams hold their spawns while the round starts
  (Variables|Default|SetFreezeUntil (+ (Variables|Default|GetClock) 3.0))
  {_sound2d(assets, "S_MixarRoundstart", 0.6)}
  (bind info (Utilities|Casting|CastToBP_MixarGameInfo :Object (Variables|Default|GetInfo))
    (:then
      (Variables|Default|SetRoundLeft (Class|BPMixarGameInfo|GetRoundSeconds :self info))
      (bind team (Class|BPMixarGameInfo|GetPlayerTeam :self info))
      (bind other (select (Utilities|String|EqualExactly(String) team "ct") "t" "ct"))
      (bind per (Math|Integer|Max(Integer) (Class|BPMixarGameInfo|GetBotsPerTeam :self info) 1))
      (CallFunction|MixarSpawnTeam :Team team :Count (- per 1) :First 1)
      (CallFunction|MixarSpawnTeam :Team other :Count per :First 0)
      (CallFunction|MixarPlacePlayer :Team team :Other other))
    (:CastFailed)))
"""),
            ("MixarPlacePlayer", [("Team", "string", False), ("Other", "string", False)], [], """
(fn MixarPlacePlayer (Team Other)
  (bind home (CallFunction|MixarSpawnCenter :Team Team))
  (bind look (Math|Rotator|FindLookatRotation :Start home :Target (CallFunction|MixarSpawnCenter :Team Other)))
  (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object (Variables|Default|GetShooter))
    (:then
      (Class|BPMixarShooterPlayer|SetTeam :self me :Team Team)
      (Class|BPMixarShooterPlayer|MixarRespawn :self me :Where home :Yaw (.yaw look)))
    (:CastFailed)))
"""),
            ("MixarSetupPlayer", [], [], """
(fn MixarSetupPlayer ()
  (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object (Variables|Default|GetShooter))
    (:then
      (Class|BPMixarShooterPlayer|MixarSetupFP :self me))
    (:CastFailed)))
"""),
            ("MixarCount", [("Team", "string", False)], [("Alive", "int")], """
(fn MixarCount (Team)
  (Variables|Default|SetTally 0)
  (for who (Variables|Default|GetBots)
    (if (and (CallFunction|MixarAlive :Who who)
             (Utilities|String|EqualExactly(String) (CallFunction|MixarTeamOf :Who who) Team))
      (Variables|Default|SetTally (+ (Variables|Default|GetTally) 1))))
  (bind me (Variables|Default|GetShooter))
  (if (and (CallFunction|MixarAlive :Who me)
           (Utilities|String|EqualExactly(String) (CallFunction|MixarTeamOf :Who me) Team))
    (Variables|Default|SetTally (+ (Variables|Default|GetTally) 1)))
  (return (Variables|Default|GetTally)))
"""),
            ("MixarEndRound", [("Winner", "string", False)], [], f"""
(fn MixarEndRound (Winner)
  (Variables|Default|SetRoundOver true)
  (bind ct (Utilities|String|EqualExactly(String) Winner "ct"))
  (if ct
    (Variables|Default|SetScoreCT (+ (Variables|Default|GetScoreCT) 1))
    (else
      (Variables|Default|SetScoreT (+ (Variables|Default|GetScoreT) 1))))
  (Variables|Default|SetBanner (select ct "Counter-Terrorists win" "Terrorists win"))
  (Variables|Default|SetBannerUntil (+ (Variables|Default|GetClock) 4.0))
  (Variables|Default|SetNextRoundAt (+ (Variables|Default|GetClock) 5.0))
  (bind info (Utilities|Casting|CastToBP_MixarGameInfo :Object (Variables|Default|GetInfo))
    (:then
      (bind mine (Utilities|String|EqualExactly(String) Winner (Class|BPMixarGameInfo|GetPlayerTeam :self info)))
      (if mine
        {_sound2d(assets, "S_MixarWin", 0.7)}
        (else
          {_sound2d(assets, "S_MixarHurt", 0.7)}))
      (bind need (Class|BPMixarGameInfo|GetRoundsToWin :self info))
      (if (>= (Math|Integer|Max(Integer) (Variables|Default|GetScoreCT) (Variables|Default|GetScoreT)) need)
        (Variables|Default|SetMatchOver true)
        (if mine
          (Variables|Default|SetWon true)
          (else
            (Variables|Default|SetLost true)))))
    (:CastFailed)))
"""),
            ("MixarReport", [], [], """
(fn MixarReport ()
  (CallFunction|ReportState :Key "round" :Value (Utilities|String|ToString(Integer) (Variables|Default|GetRoundNo)))
  (CallFunction|ReportState :Key "score_ct" :Value (Utilities|String|ToString(Integer) (Variables|Default|GetScoreCT)))
  (CallFunction|ReportState :Key "score_t" :Value (Utilities|String|ToString(Integer) (Variables|Default|GetScoreT)))
  (CallFunction|ReportState :Key "alive_ct" :Value (Utilities|String|ToString(Integer) (Variables|Default|GetAliveCT)))
  (CallFunction|ReportState :Key "alive_t" :Value (Utilities|String|ToString(Integer) (Variables|Default|GetAliveT)))
  (CallFunction|ReportState :Key "kills" :Value (Utilities|String|ToString(Integer) (Variables|Default|GetKills)))
  (CallFunction|ReportState :Key "round_left" :Value (Utilities|String|ToString(Float) (Variables|Default|GetRoundLeft)))
  (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object (Variables|Default|GetShooter))
    (:then
      (CallFunction|ReportState :Key "health"
        :Value (Utilities|String|ToString(Float) (Class|BPMixarShooterPlayer|GetHealth :self me)))
      (CallFunction|ReportState :Key "ammo"
        :Value (Utilities|String|ToString(Integer) (Class|BPMixarShooterPlayer|GetAmmo :self me)))
      (CallFunction|ReportState :Key "reserve"
        :Value (Utilities|String|ToString(Integer) (Class|BPMixarShooterPlayer|GetReserve :self me)))
      (CallFunction|ReportState :Key "player_dead"
        :Value (select (Class|BPMixarShooterPlayer|GetDead :self me) "true" "false")))
    (:CastFailed)))
"""),
        ],
        "events": f"""
(event EventBeginPlay
  (Variables|Default|SetPlayer (Game|GetPlayerCharacter :PlayerIndex 0))
  (Variables|Default|SetShooter (Game|GetPlayerCharacter :PlayerIndex 0))
  (Variables|Default|SetInfo (Actor|GetActorOfClass :ActorClass "{INFO_CLASS}"))
  (for spot (Actor|GetAllActorswithTag :Tag "mixar_role=spawn")
    (Collision|SetActorEnableCollision :self spot :bNewActorEnableCollision false)
    (Rendering|SetActorHiddenInGame :self spot :bNewHidden true)
    (if (Actor|ActorHasTag :self spot :Tag "mixar_team=t")
      (Utilities|Array|Add (Variables|Default|GetTSpawns) spot)
      (else
        (Utilities|Array|Add (Variables|Default|GetCTSpawns) spot))))
  (for stand (Actor|GetAllActorswithTag :Tag "mixar_shooter_standin")
    (Rendering|SetActorHiddenInGame :self stand :bNewHidden true)
    (Collision|SetActorEnableCollision :self stand :bNewActorEnableCollision false))
  (CallFunction|MixarSetupPlayer)
  (CallFunction|MixarReadInfo)
  (CallFunction|MixarStartRound))

(event EventTick (DeltaSeconds)
  (Variables|Default|SetClock (+ (Variables|Default|GetClock) DeltaSeconds))
  (if (not (Variables|Default|GetMatchOver))
    (Variables|Default|SetPlayTime (+ (Variables|Default|GetPlayTime) DeltaSeconds))
    (if (Variables|Default|GetRoundOver)
      (if (> (Variables|Default|GetClock) (Variables|Default|GetNextRoundAt))
        (CallFunction|MixarStartRound))
      (else
        (Variables|Default|SetRoundLeft (- (Variables|Default|GetRoundLeft) DeltaSeconds))
        (Variables|Default|SetAliveCT (CallFunction|MixarCount :Team "ct"))
        (Variables|Default|SetAliveT (CallFunction|MixarCount :Team "t"))
        (if (== (Variables|Default|GetAliveT) 0)
          (CallFunction|MixarEndRound :Winner "ct")
          (elif (== (Variables|Default|GetAliveCT) 0)
            (CallFunction|MixarEndRound :Winner "t")
            (elif (<= (Variables|Default|GetRoundLeft) 0.0)
              (CallFunction|MixarEndRound :Winner "ct")))))))
  (if (> (Variables|Default|GetClock) (Variables|Default|GetReportAt))
    (Variables|Default|SetReportAt (+ (Variables|Default|GetClock) 0.25))
    (CallFunction|MixarReport)))
""",
    }


def _text(text, x, y, scale, color, font=game_spec.ROBOTO) -> str:
    return (f'(HUD|DrawText :self self :Text {text} :TextColor {color} :ScreenX {x} :ScreenY {y} '
            f':Font "{font}" :Scale {scale} :bScalePosition false)')


def _rect(color, x, y, w, h) -> str:
    return f"(HUD|DrawRect :self self :RectColor {color} :ScreenX {x} :ScreenY {y} :ScreenW {w} :ScreenH {h})"


def _line(x1, y1, x2, y2, color, thick=2.0) -> str:
    return (f"(HUD|DrawLine :self self :StartScreenX {x1} :StartScreenY {y1} :EndScreenX {x2} :EndScreenY {y2} "
            f":LineColor {color} :LineThickness {thick})")


_rgba = game_spec._rgba  # noqa: SLF001
_PANEL = _rgba(0.0, 0.0, 0.0, 0.45)
_GREEN = _rgba(0.35, 1.0, 0.45, 0.95)
_WHITE = _rgba(1.0, 1.0, 1.0, 1.0)
_CT = _rgba(0.45, 0.7, 1.0, 1.0)
_T = _rgba(1.0, 0.72, 0.3, 1.0)
_INT = "(Utilities|String|ToString(Integer) {})"

HUD = {
    "name": "BP_MixarShooterHUD",
    "parent": "/Script/Engine.HUD",
    "functions": [game_spec.HUD["functions"][0]],
    "events": f"""
(event EventReceiveDrawHUD (SizeX SizeY)
  (bind gm (Utilities|Casting|CastToBP_MixarShooterGameMode :Object (Game|GetGameMode))
    (:then
      (bind clock (Class|BPMixarGameMode|GetClock :self gm))
      (bind cx (/ SizeX 2.0))
      (bind cy (/ SizeY 2.0))
      (bind hurt (Class|BPMixarGameMode|GetLastHurt :self gm))
      (if (and (> hurt 0.0) (< (- clock hurt) 0.35))
        {_rect(_rgba(0.8, 0.0, 0.0, "(* 0.35 (- 1.0 (/ (- clock hurt) 0.35)))"), "0.0", "0.0", "SizeX", "SizeY")})
      {_rect(_PANEL, "(- cx 150.0)", "12.0", "300.0", "58.0")}
      {_text(_INT.format('(Class|BPMixarShooterGameMode|GetScoreCT :self gm)'), "(- cx 128.0)", "20.0", 2.2, _CT)}
      {_text(_INT.format('(Class|BPMixarShooterGameMode|GetScoreT :self gm)'), "(+ cx 104.0)", "20.0", 2.2, _T)}
      (bind left (Math|Float|Max(Float) 0.0 (Class|BPMixarShooterGameMode|GetRoundLeft :self gm)))
      (bind timer (CallFunction|MixarClockText :Seconds left))
      (bind (tw th) (HUD|GetTextSize :self self :Text timer :Font "{game_spec.ROBOTO}" :Scale 1.8))
      {_text("timer", "(- cx (/ tw 2.0))", "22.0", 1.8, _WHITE)}
      {_text('(Utilities|String|Append "CT alive " ' + _INT.format('(Class|BPMixarShooterGameMode|GetAliveCT :self gm)') + ')', "(- cx 146.0)", "74.0", 1.0, _CT)}
      {_text('(Utilities|String|Append "T alive " ' + _INT.format('(Class|BPMixarShooterGameMode|GetAliveT :self gm)') + ')', "(+ cx 62.0)", "74.0", 1.0, _T)}
      (bind feed (Class|BPMixarShooterGameMode|GetFeed :self gm))
      (bind feedAt (Class|BPMixarShooterGameMode|GetFeedAt :self gm))
      (bind count (Utilities|Array|Length feed))
      (bind first (Math|Integer|Max(Integer) 0 (- count 5)))
      (for i (range first count)
        (if (< (- clock (Utilities|Array|Get(acopy) feedAt i)) 7.0)
          (bind entry (Utilities|String|Append "  " (Utilities|Array|Get(acopy) feed i)))
          (bind (ew eh) (HUD|GetTextSize :self self :Text entry :Font "{game_spec.ROBOTO}" :Scale 1.1))
          (bind y (+ 20.0 (* (- i first) 32.0)))
          {_rect(_PANEL, "(- (- SizeX ew) 34.0)", "y", "(+ ew 12.0)", "28.0")}
          {_text("entry", "(- (- SizeX ew) 28.0)", "(+ y 4.0)", 1.1, _WHITE)}))
      (if (< clock (Class|BPMixarShooterGameMode|GetBannerUntil :self gm))
        (bind banner (Class|BPMixarShooterGameMode|GetBanner :self gm))
        (bind (bw bh) (HUD|GetTextSize :self self :Text banner :Font "{game_spec.ROBOTO}" :Scale 2.6))
        {_rect(_PANEL, "(- (/ (- SizeX bw) 2.0) 24.0)", "(- (* SizeY 0.3) 10.0)", "(+ bw 48.0)", "(+ bh 20.0)")}
        {_text("banner", "(/ (- SizeX bw) 2.0)", "(* SizeY 0.3)", 2.6, _rgba(1.0, 0.85, 0.35, 1.0))})
      (if (Class|BPMixarShooterGameMode|GetMatchOver :self gm)
        {_rect(_rgba(0.0, 0.0, 0.0, 0.55), "0.0", "0.0", "SizeX", "SizeY")}
        (bind result (select (Class|BPMixarGameMode|GetWon :self gm) "Match won" "Match lost"))
        (bind (rw rh) (HUD|GetTextSize :self self :Text result :Font "{game_spec.ROBOTO}" :Scale 4.0))
        {_text("result", "(/ (- SizeX rw) 2.0)", "(- cy rh)", 4.0, _rgba(1.0, 0.82, 0.3, 1.0))}
        (bind line (Utilities|String|Append (Utilities|String|Append "CT  " {_INT.format('(Class|BPMixarShooterGameMode|GetScoreCT :self gm)')})
                     (Utilities|String|Append "  :  " (Utilities|String|Append {_INT.format('(Class|BPMixarShooterGameMode|GetScoreT :self gm)')} "  T"))))
        (bind (lw lh) (HUD|GetTextSize :self self :Text line :Font "{game_spec.ROBOTO}" :Scale 1.8))
        {_text("line", "(/ (- SizeX lw) 2.0)", "(+ cy 20.0)", 1.8, _WHITE)})
      (bind me (Utilities|Casting|CastToBP_MixarShooterPlayer :Object (Class|BPMixarShooterGameMode|GetShooter :self gm))
        (:then
          (bind dead (Class|BPMixarShooterPlayer|GetDead :self me))
          (if (not dead)
            (bind gap (+ 5.0 (* (Class|BPMixarShooterPlayer|GetSpread :self me) 5.0)))
            {_rect(_GREEN, "(- cx 1.0)", "(- (- cy gap) 9.0)", "2.0", "9.0")}
            {_rect(_GREEN, "(- cx 1.0)", "(+ cy gap)", "2.0", "9.0")}
            {_rect(_GREEN, "(- (- cx gap) 9.0)", "(- cy 1.0)", "9.0", "2.0")}
            {_rect(_GREEN, "(+ cx gap)", "(- cy 1.0)", "9.0", "2.0")}
            (bind sinceHit (- clock (Class|BPMixarShooterGameMode|GetLastHitAt :self gm)))
            (if (< sinceHit 0.2)
              (bind hc (select (< (- clock (Class|BPMixarShooterGameMode|GetLastHeadshotAt :self gm)) 0.2)
                         {_rgba(1.0, 0.25, 0.2, 1.0)} {_WHITE}))
              {_line("(- cx 12.0)", "(- cy 12.0)", "(- cx 5.0)", "(- cy 5.0)", "hc")}
              {_line("(+ cx 12.0)", "(- cy 12.0)", "(+ cx 5.0)", "(- cy 5.0)", "hc")}
              {_line("(- cx 12.0)", "(+ cy 12.0)", "(- cx 5.0)", "(+ cy 5.0)", "hc")}
              {_line("(+ cx 12.0)", "(+ cy 12.0)", "(+ cx 5.0)", "(+ cy 5.0)", "hc")}))
          {_rect(_PANEL, "24.0", "(- SizeY 76.0)", "300.0", "52.0")}
          {_text('(Utilities|String|Append "+  " ' + _INT.format('(Math|Float|Round (Class|BPMixarShooterPlayer|GetHealth :self me))') + ')', "40.0", "(- SizeY 68.0)", 1.8, _WHITE)}
          {_text('(Utilities|String|Append "ARMOR  " ' + _INT.format('(Math|Float|Round (Class|BPMixarShooterPlayer|GetArmor :self me))') + ')', "170.0", "(- SizeY 62.0)", 1.3, _rgba(0.8, 0.85, 0.95, 1.0))}
          {_rect(_PANEL, "(- SizeX 214.0)", "(- SizeY 76.0)", "190.0", "52.0")}
          {_text('(Utilities|String|Append ' + _INT.format('(Class|BPMixarShooterPlayer|GetAmmo :self me)') + ' (Utilities|String|Append "  /  " ' + _INT.format('(Class|BPMixarShooterPlayer|GetReserve :self me)') + '))', "(- SizeX 196.0)", "(- SizeY 68.0)", 1.8, _WHITE)}
          (if (Class|BPMixarShooterPlayer|GetReloading :self me)
            {_text('"Reloading"', "(- SizeX 196.0)", "(- SizeY 100.0)", 1.2, _rgba(1.0, 0.85, 0.4, 1.0))})
          (if dead
            (bind (mw mh) (HUD|GetTextSize :self self :Text "You were killed. Next round soon." :Font "{game_spec.ROBOTO}" :Scale 1.6))
            {_text('"You were killed. Next round soon."', "(/ (- SizeX mw) 2.0)", "(* SizeY 0.7)", 1.6, _rgba(1.0, 0.5, 0.45, 1.0))}))
        (:CastFailed)))
    (:CastFailed)))
""",
}


def specs(assets: dict) -> list:
    """Build order: the bot, the player, the game mode, the HUD."""
    return [bot(assets), player(assets), game_mode(assets), HUD]
