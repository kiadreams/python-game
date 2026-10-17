import pygame

# =============================================================================
# 1. CONSTANTS & SCALE FACTORS (SI units)
# =============================================================================

WINDOW_WIDTH = 1200  # px
WINDOW_HEIGHT = 700  # px
FPS = 60  # Hz (was 120: half the frames = half the CPU load, still smooth)

# Scale between the physics world and the screen: 1 physical metre = 80 px
PIXELS_PER_METER = 80.0

GRAVITY = 9.81  # m/s^2 (screen y axis points down)
GROUND_LEVEL_M = 7.20  # ground height in the physics world [m]

CAMERA_STIFFNESS = 15.0  # camera follow speed (higher = snappier)
CAMERA_LOOKAHEAD_S = 0.30  # the camera aims this many seconds ahead of the runner

# Realism / game feel
STRIDE_LENGTH_M = 1.4  # distance covered during one full leg cycle
JUMP_BUFFER_S = 0.12  # a jump pressed this early before landing still counts
JUMP_CUT = 0.5  # upward speed factor when the jump key is released early

# Collectible energy orbs
ORB_CELL_M = 9.0  # the world is split into cells of this width
ORB_PICKUP_RADIUS_M = 0.6  # pickup distance from the centre of mass G

# Colours
COLOR_SKY_TOP = (4, 8, 22)
COLOR_SKY_HORIZON = (46, 60, 116)
COLOR_MOUNTAINS = ((38, 50, 98), (28, 40, 84), (20, 31, 68))  # far -> near
COLOR_FOG = (92, 110, 182)
COLOR_TREES_BACK = (15, 26, 56)
COLOR_TREES_FRONT = (8, 14, 34)
COLOR_MOON = (226, 232, 240)
COLOR_MOON_CRATER = (198, 208, 226)
COLOR_CLOUD = (132, 148, 208)
COLOR_GROUND = (2, 6, 23)
COLOR_GROUND_TOP = (20, 28, 54)
COLOR_GROUND_LINE = (34, 197, 94)
COLOR_GRASS_A = (21, 128, 61)
COLOR_GRASS_B = (22, 163, 74)
COLOR_PEBBLE = (32, 44, 70)
COLOR_GRID_MAJOR = (71, 85, 105)
COLOR_MARKER = (56, 189, 248)
COLOR_LABEL = (148, 163, 184)
COLOR_STICKMAN = (248, 250, 252)
COLOR_STICKMAN_BACK = (148, 163, 184)
COLOR_CENTER = (239, 68, 68)
COLOR_VELOCITY = (250, 204, 21)
COLOR_TEXT = (241, 245, 249)
COLOR_GOOD = (74, 222, 128)
COLOR_BAD = (248, 113, 113)
COLOR_DUST = (122, 134, 156)
COLOR_ORB = (168, 85, 247)
COLOR_ORB_CORE = (216, 180, 254)
COLOR_FIREFLY = (190, 242, 100)
COLOR_KNIFE_BLADE = (226, 232, 240)
COLOR_KNIFE_SHINE = (255, 255, 255)
COLOR_KNIFE_HANDLE = (146, 84, 44)
COLOR_KNIFE_GUARD = (250, 204, 21)
COLOR_ZOMBIE_EYE = (255, 70, 70)
COLOR_HEART = (239, 68, 68)
COLOR_HEART_EMPTY = (51, 65, 85)
COLOR_BONE = (226, 232, 240)
GORE_COLORS = ((120, 24, 28), (160, 34, 34), (92, 140, 64), (62, 104, 52))

# Menu / shop / weapons
COLOR_PANEL = (15, 23, 42)
COLOR_PANEL_EDGE = (71, 85, 105)
COLOR_BUTTON = (30, 41, 59)
COLOR_BUTTON_HOVER = (51, 65, 85)
COLOR_ACCENT = (56, 189, 248)
COLOR_METAL = (148, 163, 184)
COLOR_METAL_DARK = (71, 85, 105)
COLOR_GRIP = (120, 72, 40)
COLOR_OLIVE = (90, 110, 70)
COLOR_ROCKET_TIP = (239, 68, 68)
COLOR_BULLET = (254, 240, 138)
COLOR_FIRE = (251, 146, 60)
COLOR_FIRE_CORE = (253, 224, 71)
COLOR_SMOKE = (148, 163, 184)

JUMP_KEYS = (pygame.K_SPACE, pygame.K_UP, pygame.K_w, pygame.K_z)
THROW_KEYS = (pygame.K_f, pygame.K_j)

# Knives
KNIFE_SPEED = 15.0  # launch speed [m/s]
KNIFE_GRAVITY_FACTOR = 0.22  # knives fall slower than real gravity -> a flat, readable arc
KNIFE_SPIN_RAD_S = 26.0  # spin speed while flying [rad/s]
KNIFE_COOLDOWN_S = 0.28  # minimum delay between two throws [s]
KNIFE_LIFETIME_S = 1.8  # a knife that hit nothing disappears after this [s]
KNIFE_STUCK_S = 1.2  # how long a knife stays stuck in the ground [s]
THROW_TIME_S = 0.24  # length of the throwing animation [s]
THROW_RELEASE_AT = 0.5  # the knife leaves the hand at this fraction of the animation
MAX_KNIVES = 24

# Zombies
ZOMBIE_MAX_ALIVE = 8
ZOMBIE_SPAWN_MIN_S = 1.4  # random delay between two spawns [s]
ZOMBIE_SPAWN_MAX_S = 3.6
ZOMBIE_SPAWN_DIST_M = (9.5, 13.0)  # spawn distance from the player (just off-screen) [m]
ZOMBIE_DESPAWN_DIST_M = 40.0
ZOMBIE_CORPSE_S = 2.2  # how long a corpse stays before it is removed [s]
ZOMBIE_ATTACK_PAUSE_S = 0.9  # a zombie stops for a moment after biting [s]
ZOMBIES_HURT_PLAYER = True  # False = harmless zombies (pure target practice)
PLAYER_MAX_HP = 5
INVULNERABLE_S = 1.2  # blinking invulnerability after a bite [s]

# Economy: orbs are the money. Every orb picked up = 1, every zombie killed = KILL_REWARD.
KILL_REWARD = 1
MAX_SHOTS = 60  # bullets / rockets in the air at the same time
ROCKET_BLAST_RADIUS_M = 2.4  # a rocket explosion hurts every zombie this close [m]
SHOP_MEDKIT_HEAL = 2  # hearts restored by a medkit

START_FULLSCREEN = True  # True = start in full-screen mode (F11 switches it at any time; also:
# --fullscreen)

# Weapons. The knife is free, the others are bought in the shop with orbs (prices are in orbs - change them here!)
#   cost: price | cooldown: delay between two shots [s] | speed: muzzle speed [m/s]
#   damage: hp taken from a zombie | spread: random aim error [rad]
#   anim / release_at: length of the throw animation and the moment the projectile leaves the hand
#   (names and descriptions are translated: see "weapon.<key>.name" / "weapon.<key>.desc" in the table below)
WEAPON_ORDER = ("knife", "pistol", "smg", "rocket")
WEAPONS = {
    "knife": {"cost": 0, "cooldown": KNIFE_COOLDOWN_S, "speed": KNIFE_SPEED,
              "damage": 1, "spread": 0.0, "anim": THROW_TIME_S, "release_at": THROW_RELEASE_AT},
    "pistol": {"cost": 12, "cooldown": 0.32, "speed": 34.0,
               "damage": 2, "spread": 0.02, "anim": 0.14, "release_at": 0.0},
    "smg": {"cost": 30, "cooldown": 0.09, "speed": 30.0,
            "damage": 1, "spread": 0.07, "anim": 0.14, "release_at": 0.0},
    "rocket": {"cost": 50, "cooldown": 1.10, "speed": 12.0,
               "damage": 4, "spread": 0.0, "anim": 0.14, "release_at": 0.0},
}

# Upgrades. costs = price of each level (the list length is the max level); repeat = can be bought again and again
# (names and descriptions: "upgrade.<key>.name" / "upgrade.<key>.desc" in the translation table below)
UPGRADE_ORDER = ("medkit", "heart", "damage", "rate", "boots")
UPGRADES = {
    "medkit": {"costs": (6,), "repeat": True},
    "heart": {"costs": (15, 25, 40)},
    "damage": {"costs": (25, 45)},
    "rate": {"costs": (18, 30, 45)},
    "boots": {"costs": (14, 24)},
}
