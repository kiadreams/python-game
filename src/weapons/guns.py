import math
import random

from game_config.const import *
from .knife import draw_knife


# =============================================================================
# 5b2. GUNS, BULLETS & ROCKETS (weapons bought in the shop)
# =============================================================================

def draw_weapon(surface, kind, cx, cy, angle, s=1.0):
    """Gun sprite around the hand (cx, cy); `angle` = direction the muzzle points on screen."""
    c, sn = math.cos(angle), math.sin(angle)
    m = -1.0 if c < 0.0 else 1.0  # mirrored when aiming left, so it is never upside down

    def pt(u, v):  # u along the barrel, v across it (positive = down)
        v *= m
        return (cx + (c * u - sn * v) * s, cy + (sn * u + c * v) * s)

    if kind == "pistol":
        pygame.draw.polygon(surface, COLOR_GRIP, [pt(0, 0), pt(7, 0), pt(5, 11), pt(-1, 11)])
        pygame.draw.polygon(surface, COLOR_METAL, [pt(-2, -5), pt(20, -5), pt(20, 1), pt(-2, 1)])
        pygame.draw.line(surface, COLOR_METAL_DARK, pt(-2, 1), pt(20, 1), 1)
    elif kind == "smg":
        pygame.draw.polygon(surface, COLOR_GRIP, [pt(-1, 1), pt(5, 1), pt(4, 11), pt(-2, 11)])
        pygame.draw.polygon(surface, COLOR_METAL_DARK,
                            [pt(10, 1), pt(15, 1), pt(14, 16), pt(9, 16)])  # magazine
        pygame.draw.line(surface, COLOR_METAL_DARK, pt(-3, -2), pt(-13, 3), 3)  # stock
        pygame.draw.polygon(surface, COLOR_METAL, [pt(-3, -5), pt(26, -5), pt(26, 1), pt(-3, 1)])
        pygame.draw.line(surface, COLOR_METAL_DARK, pt(26, -3), pt(36, -3), 3)  # barrel
    elif kind == "rocket":
        pygame.draw.polygon(surface, COLOR_GRIP, [pt(2, 3), pt(8, 3), pt(7, 12), pt(1, 12)])
        pygame.draw.polygon(surface, COLOR_OLIVE, [pt(-14, -8), pt(24, -8), pt(24, 3), pt(-14, 3)])
        pygame.draw.polygon(surface, COLOR_METAL_DARK,
                            [pt(24, -9), pt(28, -9), pt(28, 4), pt(24, 4)])  # muzzle ring
        pygame.draw.polygon(surface, COLOR_ROCKET_TIP,
                            [pt(28, -6), pt(36, -2.5), pt(28, 1)])  # warhead
        pygame.draw.line(surface, COLOR_METAL, pt(2, -8), pt(2, -13), 2)  # sight


# Centre of each sprite in its own (u, v) coordinates, so icons can be centred in a slot
ICON_CENTER = {"pistol": (9, 3), "smg": (11, 5), "rocket": (11, 2)}


def draw_weapon_icon(surface, key, cx, cy, s=1.0):
    """Weapon picture centred on (cx, cy) - used in the HUD slots and in the shop."""
    if key == "knife":
        draw_knife(surface, cx - 3, cy, 0.0)
    else:
        ox, oy = ICON_CENTER[key]
        draw_weapon(surface, key, cx - ox * s, cy - oy * s, 0.0, s)


class Projectile:
    """A bullet or a rocket: a point mass flying (almost) straight."""

    __slots__ = ("kind", "x", "y", "prev_x", "prev_y", "vx", "vy", "damage", "age", "dead", "angle")

    LIFETIME_S = {"bullet": 1.4, "rocket": 3.0}
    GRAVITY_FACTOR = {"bullet": 0.0, "rocket": 0.06}

    def __init__(self, kind, x_m, y_m, vx, vy, damage):
        self.kind = kind  # "bullet" | "rocket"
        self.x, self.y = x_m, y_m  # world position [m]
        self.prev_x, self.prev_y = x_m, y_m  # previous position (for the swept hit test)
        self.vx, self.vy = vx, vy  # [m/s]
        self.damage = damage
        self.age = 0.0
        self.dead = False
        self.angle = math.atan2(vy, vx)

    def update(self, dt, ground_level_m):
        """Returns True on the frame the projectile hits the ground."""
        self.age += dt
        self.prev_x, self.prev_y = self.x, self.y
        self.vy += GRAVITY * self.GRAVITY_FACTOR[self.kind] * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle = math.atan2(self.vy, self.vx)
        if self.y >= ground_level_m:
            self.y = ground_level_m
            self.dead = True
            return True
        if self.age > self.LIFETIME_S[self.kind]:
            self.dead = True
        return False

    def draw(self, surface, camera_x):
        sx = self.x * PIXELS_PER_METER - camera_x
        sy = self.y * PIXELS_PER_METER
        if sx < -60 or sx > WINDOW_WIDTH + 60:
            return
        c, s = math.cos(self.angle), math.sin(self.angle)
        if self.kind == "bullet":
            tail = (sx - c * 16, sy - s * 16)
            pygame.draw.line(surface, COLOR_FIRE, tail, (sx, sy), 3)
            pygame.draw.line(surface, COLOR_BULLET, tail, (sx, sy), 1)
            return

        def pt(u, v):
            return (sx + c * u - s * v, sy + s * u + c * v)

        flame = 8 + random.random() * 8
        pygame.draw.polygon(surface, COLOR_FIRE, [pt(-11, -3), pt(-11 - flame, 0), pt(-11, 3)])
        pygame.draw.polygon(surface, COLOR_FIRE_CORE,
                            [pt(-11, -1.5), pt(-11 - flame * 0.6, 0), pt(-11, 1.5)])
        pygame.draw.polygon(surface, COLOR_METAL_DARK,
                            [pt(-12, -3.5), pt(-17, -7), pt(-7, -3.5)])  # fins
        pygame.draw.polygon(surface, COLOR_METAL_DARK, [pt(-12, 3.5), pt(-17, 7), pt(-7, 3.5)])
        pygame.draw.polygon(surface, COLOR_METAL,
                            [pt(-12, -3.5), pt(8, -3.5), pt(8, 3.5), pt(-12, 3.5)])
        pygame.draw.polygon(surface, COLOR_ROCKET_TIP, [pt(8, -3.5), pt(16, 0), pt(8, 3.5)])


def blast_zombies(x_m, y_m, damage, radius_m, zombies, ground_level_m, particles):
    """Rocket explosion: every living zombie within `radius_m` takes `damage`. Returns the number of kills."""
    killed = 0
    height = ground_level_m - y_m
    for z in zombies:
        if z.state != "walk":
            continue
        dx = z.x - x_m
        dy = height - 0.7 * z.scale  # vertical distance to the middle of the body
        if math.hypot(dx, dy) > radius_m + 0.3 * z.scale:
            continue
        push = 1 if dx >= 0.0 else -1
        died = z.hit(push, damage)
        particles.gore(z.x, ground_level_m - 0.7 * z.scale, 16 if died else 6, push)
        if died:
            killed += 1
    return killed
