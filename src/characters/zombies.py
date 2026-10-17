import math
import random

import pygame

from game_config.const import (
    ZOMBIE_CORPSE_S,
    PIXELS_PER_METER,
    COLOR_GROUND_TOP,
    COLOR_ZOMBIE_EYE,
    COLOR_BAD, COLOR_GRID_MAJOR
)
from helper_func import clamp, lerp_color
from helper_func import get_shadow_sprite

# =============================================================================
# 5c. ZOMBIES
# =============================================================================

ZOMBIE_TYPES = {
    # scale: size factor | speed: random range [m/s] | hp: knife hits needed to kill
    "walker": {"scale": 1.00, "speed": (0.8, 1.3), "hp": 2,
               "skin": (118, 170, 96), "cloth": (92, 108, 150), "pants": (48, 56, 88)},
    "runner": {"scale": 0.92, "speed": (2.5, 3.2), "hp": 2,
               "skin": (170, 190, 100), "cloth": (160, 90, 90), "pants": (70, 50, 70)},
    "brute": {"scale": 1.30, "speed": (0.6, 0.9), "hp": 4,
              "skin": (88, 134, 82), "cloth": (80, 70, 110), "pants": (42, 40, 62)},
    # The boss of the story (never spawns by itself). boss: no health pips | bite: hearts per bite | shove: knock-back factor
    "warden": {"scale": 1.75, "speed": (0.7, 0.9), "hp": 84, "boss": True, "bite": 2, "shove": 0.15,
               "skin": (150, 96, 90), "cloth": (120, 36, 44), "pants": (44, 28, 40)},
    # The mid-game boss (chapter 5): a bit smaller and quicker than the Keeper, white apron
    "butcher": {"scale": 1.5, "speed": (0.9, 1.2), "hp": 54, "boss": True, "bite": 2, "shove": 0.2,
                "skin": (128, 150, 100), "cloth": (206, 206, 212), "pants": (70, 44, 44)},
}
ZOMBIE_WEIGHTS = (("walker", 0.60), ("runner", 0.25), ("brute", 0.15))
ZOMBIE_FALL_MAX = 1.52  # corpse angle when lying down [rad] (~87 deg)
ZOMBIE_FADE_START_S = 1.3  # corpses start to melt into the ground after this


def pick_zombie_kind(weights=ZOMBIE_WEIGHTS):
    """Random zombie type; `weights` = ((kind, weight), ...)."""
    r = random.random() * sum(w for _, w in weights)
    acc = 0.0
    for kind, weight in weights:
        acc += weight
        if r < acc:
            return kind
    return weights[-1][0]


class Zombie:
    """A shambling zombie that walks towards the player and dies from knife hits."""

    def __init__(self, x_m, kind="walker"):
        cfg = ZOMBIE_TYPES[kind]
        self.kind = kind
        self.cfg = cfg
        self.scale = cfg["scale"]
        self.max_hp = self.hp = cfg["hp"]
        self.speed = random.uniform(*cfg["speed"])  # walking speed [m/s]
        self.x = x_m  # world position of the feet [m]
        self.vx = 0.0
        self.facing = 1
        self.phase = random.uniform(0.0, math.tau)  # stride cycle angle [rad]
        self.state = "walk"  # "walk" | "dying"
        self.hit_flash = 0.0  # white flash when hit [s]
        self.attack_cd = 0.0  # pause after biting [s]
        self.death_time = 0.0
        self.fall_angle = 0.0  # 0 = upright .. ZOMBIE_FALL_MAX = lying
        self.fall_speed = 0.0
        self.fall_k = 1.0  # +1 falls backwards, -1 falls forwards
        self.remove = False

    # ------------------------------------------------------------ behaviour

    def update(self, dt, player_x):
        if self.state == "dying":
            self.death_time += dt
            self.fall_speed += 16.0 * dt
            self.fall_angle = min(ZOMBIE_FALL_MAX, self.fall_angle + self.fall_speed * dt)
            self.vx *= math.exp(-5.0 * dt)
            self.x += self.vx * dt
            if self.death_time > ZOMBIE_CORPSE_S:
                self.remove = True
            return

        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.attack_cd = max(0.0, self.attack_cd - dt)

        dx = player_x - self.x
        if abs(dx) > 0.05:
            self.facing = 1 if dx > 0.0 else -1

        # Shuffle towards the player; stand still right after a bite or when on top of him
        if self.attack_cd > 0.0 or abs(dx) < 0.3:
            target = 0.0
        else:
            target = self.facing * self.speed
        self.vx += (target - self.vx) * (1.0 - math.exp(-5.0 * dt))
        self.x += self.vx * dt
        self.phase += abs(self.vx) * (math.tau / (0.9 * self.scale)) * dt

    def hit(self, push_dir, damage=1):
        """A hit. `push_dir` = +1 / -1 is the direction the knife / bullet was flying.
        Returns True if the zombie died from it."""
        self.hp -= damage
        self.hit_flash = 0.12
        if self.hp <= 0:
            self.state = "dying"
            self.fall_speed = 1.5
            self.death_time = 0.0
            self.vx = push_dir * 2.5
            self.fall_k = -push_dir * self.facing  # fall away from the knife
            return True
        self.vx = push_dir * 2.2 * self.cfg.get("shove",
                                                1.0)  # a tougher zombie is only shoved back
        return False

    def hit_by(self, x0, y0, x1, y1, ground_level_m):
        """Swept box test of a knife that moved from (x0, y0) to (x1, y1) this frame."""
        half_w = 0.30 * self.scale + 0.08
        top = ground_level_m - 1.40 * self.scale
        if max(x0, x1) < self.x - half_w or min(x0, x1) > self.x + half_w:
            return False
        return not (max(y0, y1) < top or min(y0, y1) > ground_level_m)

    def touches(self, player, ground_level_m):
        """True if the zombie can bite the player (jump over it to dodge)."""
        if self.state != "walk" or self.attack_cd > 0.0:
            return False
        feet_height = ground_level_m - (player.position.y + player.height_m / 2.0)
        reach = 0.30 * self.scale + 0.22
        return abs(player.position.x - self.x) < reach and feet_height < 0.8 * self.scale

    # -------------------------------------------------------------- drawing

    def draw_shadow(self, surface, camera_x, ground_level_m):
        if self.state == "dying":
            return
        width, thick = int(46 * self.scale), max(3, int(9 * self.scale))
        sprite = get_shadow_sprite(width, thick, 110)
        gx = self.x * PIXELS_PER_METER - camera_x - 6
        surface.blit(sprite,
                     (int(gx - width / 2), int(ground_level_m * PIXELS_PER_METER - thick / 2 + 2)))

    def draw(self, surface, camera_x, ground_level_m):
        ppm = PIXELS_PER_METER
        s = self.scale
        f = self.facing
        foot_x = self.x * ppm - camera_x
        ground_px = ground_level_m * ppm
        cfg = self.cfg

        # Corpses melt into the ground colour at the end
        fade = 0.0
        if self.state == "dying":
            fade = clamp(
                (self.death_time - ZOMBIE_FADE_START_S) / (ZOMBIE_CORPSE_S - ZOMBIE_FADE_START_S),
                0.0, 1.0)
        flash = self.hit_flash > 0.0

        def col(c):
            if flash:
                c = lerp_color(c, (255, 255, 255), 0.75)
            if fade > 0.0:
                c = lerp_color(c, COLOR_GROUND_TOP, fade)
            return c

        # Rotation of the whole body about the feet (falling over)
        phi = self.fall_angle * self.fall_k
        cp, sp = math.cos(phi), math.sin(phi)

        def pt(x, y):
            """Body-local metres (x forward, y up from the feet) -> screen pixels."""
            xr = x * cp - y * sp
            yr = max(0.0, x * sp + y * cp)
            return (foot_x + f * xr * ppm, ground_px - yr * ppm)

        def ipt(x, y):
            px, py = pt(x, y)
            return (int(px), int(py))

        # --- Pose -----------------------------------------------------------
        alive = self.state == "walk"
        moving = min(abs(self.vx) / 0.8, 1.0) if alive else 0.0
        swing = math.sin(self.phase) * 0.55 * moving
        leg_len, torso_len = 0.55 * s, 0.47 * s
        head_r, arm_len = 0.15 * s, 0.52 * s

        hip = (0.0, leg_len * math.cos(swing))  # hips dip while striding
        foot_a = (hip[0] + math.sin(swing) * leg_len, 0.0)
        foot_b = (hip[0] - math.sin(swing) * leg_len, 0.0)
        lean = 0.22
        shoulder = (hip[0] + math.sin(lean) * torso_len, hip[1] + math.cos(lean) * torso_len)
        head = (shoulder[0] + math.sin(lean) * (head_r + 0.02),
                shoulder[1] + math.cos(lean) * (head_r + 0.02))
        # Arms stretched out in front (they drop when the zombie is dying)
        droop = min(1.0, self.death_time * 3.0) if not alive else 0.0
        up_a = 0.18 + 0.10 * math.sin(self.phase + 1.3) - 1.7 * droop
        up_b = 0.30 + 0.10 * math.sin(self.phase + 3.1) - 1.7 * droop
        hand_a = (shoulder[0] + math.cos(up_a) * arm_len, shoulder[1] + math.sin(up_a) * arm_len)
        hand_b = (shoulder[0] + math.cos(up_b) * arm_len, shoulder[1] + math.sin(up_b) * arm_len)

        skin, cloth, pants = col(cfg["skin"]), col(cfg["cloth"]), col(cfg["pants"])
        skin_dark = col(lerp_color(cfg["skin"], (0, 0, 0), 0.35))
        leg_w, arm_w, torso_w = max(3, int(5 * s)), max(3, int(4 * s)), max(4, int(7 * s))

        # Blood pool under a fresh corpse
        if self.state == "dying" and self.death_time > 0.3:
            d = -self.fall_k * f
            w = int(80 * s * min(1.0, (self.death_time - 0.3) / 1.2))
            if w > 2:
                pool = col((70, 18, 26))
                pygame.draw.ellipse(surface, pool,
                                    (int(foot_x + d * 0.6 * s * ppm - w / 2), int(ground_px - 3), w,
                                     9))

        # Back limbs, torso, head, front limbs
        pygame.draw.line(surface, col(lerp_color(cfg["pants"], (0, 0, 0), 0.3)), pt(*hip),
                         pt(*foot_b), leg_w)
        pygame.draw.line(surface, skin_dark, pt(*shoulder), pt(*hand_b), arm_w)
        pygame.draw.line(surface, cloth, pt(*hip), pt(*shoulder), torso_w)
        hc = ipt(*head)
        pygame.draw.circle(surface, skin, hc, max(5, int(head_r * ppm)))
        pygame.draw.circle(surface, COLOR_ZOMBIE_EYE, ipt(head[0] + 0.07 * s, head[1] + 0.03 * s),
                           max(2, int(2.3 * s)))
        pygame.draw.line(surface, pants, pt(*hip), pt(*foot_a), leg_w)
        pygame.draw.line(surface, skin, pt(*shoulder), pt(*hand_a), arm_w)

        # Little health pips for tougher zombies
        if alive and self.hp < self.max_hp and not cfg.get("boss"):
            bx = int(foot_x - self.max_hp * 5)
            by = int(ground_px - 1.55 * s * ppm)
            for i in range(self.max_hp):
                color = COLOR_BAD if i < self.hp else COLOR_GRID_MAJOR
                pygame.draw.rect(surface, color, (bx + i * 10, by, 8, 4))
