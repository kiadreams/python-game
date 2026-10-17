import math

from game_config.const import *


# =============================================================================
# 5b. KNIVES (thrown weapon)
# =============================================================================

def draw_knife(surface, cx, cy, angle):
    """A small throwing knife centred on (cx, cy); `angle` = direction of the tip on screen."""
    c, s = math.cos(angle), math.sin(angle)

    def pt(u, v):  # u along the blade, v across it
        return (cx + c * u - s * v, cy + s * u + c * v)

    pygame.draw.line(surface, COLOR_KNIFE_HANDLE, pt(-13, 0), pt(-4, 0), 4)
    pygame.draw.line(surface, COLOR_KNIFE_GUARD, pt(-4, -4), pt(-4, 4), 2)
    pygame.draw.polygon(surface, COLOR_KNIFE_BLADE,
                        [pt(-3, -2.5), pt(12, -2.5), pt(20, 0.5), pt(12, 2.5), pt(-3, 2.5)])
    pygame.draw.line(surface, COLOR_KNIFE_SHINE, pt(0, -1), pt(14, -1), 1)


class Knife:
    """A thrown knife: a small point mass flying on a flat arc while it spins."""

    __slots__ = ("x", "y", "prev_x", "prev_y", "vx", "vy", "angle", "spin",
                 "age", "stuck", "stuck_time", "dead", "damage")

    def __init__(self, x_m, y_m, vx, vy, damage=1):
        self.damage = damage  # hp taken from a zombie
        self.x, self.y = x_m, y_m  # world position [m]
        self.prev_x, self.prev_y = x_m, y_m  # previous position (for the swept hit test)
        self.vx, self.vy = vx, vy  # [m/s]
        self.angle = math.atan2(vy, vx)  # where the tip points on screen [rad]
        self.spin = KNIFE_SPIN_RAD_S if vx >= 0.0 else -KNIFE_SPIN_RAD_S
        self.age = 0.0
        self.stuck = False
        self.stuck_time = 0.0
        self.dead = False

    def update(self, dt, ground_level_m):
        """Returns True on the frame the knife sticks into the ground."""
        self.age += dt
        if self.stuck:
            self.stuck_time -= dt
            return False
        self.prev_x, self.prev_y = self.x, self.y
        self.vy += GRAVITY * KNIFE_GRAVITY_FACTOR * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        if self.y >= ground_level_m:
            self.y = ground_level_m
            self.stuck = True
            self.stuck_time = KNIFE_STUCK_S
            self.angle = math.pi / 2.0 + (0.4 if self.vx >= 0.0 else -0.4)
            return True
        if self.age > KNIFE_LIFETIME_S:
            self.dead = True
        return False

    def draw(self, surface, camera_x):
        sx = self.x * PIXELS_PER_METER - camera_x
        sy = self.y * PIXELS_PER_METER
        if sx < -40 or sx > WINDOW_WIDTH + 40:
            return
        if self.stuck:
            # The tip is buried in the ground, the handle sticks out
            sx -= math.cos(self.angle) * 17
            sy -= math.sin(self.angle) * 17
        draw_knife(surface, sx, sy, self.angle)
