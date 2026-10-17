import functools
import json
import math
import os
import random
import sys
from pathlib import Path

from characters.zombies import ZOMBIE_WEIGHTS, Zombie, pick_zombie_kind
from characters.stickman import Stickman
from game_config.const import *
from game_config.languages import _T
from helper_func import hash01, clamp, lerp, lerp_color, make_glow
from weapons import draw_weapon_icon, blast_zombies, Knife, Projectile

# =============================================================================
# 1b. LANGUAGES: English, Spanish, French, Russian
# =============================================================================
# Every text of the game lives in _T:  "key": (English, Español, Français, Русский)  - same order as LANGUAGES.
# To add a sentence: add a row here and call tr("key"). Placeholders like {n} are filled in by tr("key", n=5);
# a keyword that ends with "_key" (e.g. what_key="c1.reward") is translated first, then inserted.

LANGUAGES = ("en", "es", "fr", "ru")
LANGUAGE_NAMES = {"en": "English", "es": "Español", "fr": "Français", "ru": "Русский"}
DEFAULT_LANGUAGE = "ru"

_LANG_INDEX = {code: i for i, code in enumerate(LANGUAGES)}

# ------------------------------------------------------------------ settings (language + unlocked chapters)

try:
    SETTINGS_PATH = Path(__file__).with_name("app_settings.json")
except NameError:  # not run from a file (e.g. pasted into a console)
    SETTINGS_PATH = Path("app_settings.json")


def load_settings():
    data = {"lang": DEFAULT_LANGUAGE, "unlocked": 0}
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if raw.get("lang") in LANGUAGES:
            data["lang"] = raw["lang"]
        data["unlocked"] = max(0, int(raw.get("unlocked", 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # no file yet / broken file: just use the defaults
    return data


def save_settings():
    try:
        SETTINGS_PATH.write_text(json.dumps(SETTINGS, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except OSError:
        pass  # read-only folder: the game still works, it just forgets


SETTINGS = load_settings()


def get_language():
    return SETTINGS["lang"]


def set_language(code):
    if code in _LANG_INDEX and code != SETTINGS["lang"]:
        SETTINGS["lang"] = code
        save_settings()


def next_language():
    return LANGUAGES[(_LANG_INDEX[get_language()] + 1) % len(LANGUAGES)]


def tr(key, **kw):
    """The text `key` in the current language (an unknown key is returned as it is, so a typo is easy to spot)."""
    row = _T.get(key)
    if row is None:
        return key
    text = row[_LANG_INDEX[get_language()]]
    if kw:
        for name in [n for n in kw if n.endswith("_key")]:
            kw[name[:-4]] = tr(kw.pop(name))
        text = text.format(**kw)
    return text


def tr_spec(spec):
    """A message that is stored now and translated when it is drawn: either "key" or ("key", {kwargs})."""
    return tr(spec) if isinstance(spec, str) else tr(spec[0], **spec[1])


def weapon_name(key):
    return tr(f"weapon.{key}.name")


def weapon_desc(key):
    return tr(f"weapon.{key}.desc")


def upgrade_name(key):
    return tr(f"upgrade.{key}.name")


def upgrade_desc(key):
    return tr(f"upgrade.{key}.desc")


# =============================================================================
# 3. PARTICLES (dust, sparkles, gore)
# =============================================================================

class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "grow",
                 "color", "alpha", "gravity", "drag")

    def __init__(self, x, y, vx, vy, life, size, grow, color, alpha, gravity, drag):
        self.x, self.y = x, y  # world position [m]
        self.vx, self.vy = vx, vy  # [m/s]
        self.life = self.max_life = life  # [s]
        self.size, self.grow = size, grow  # radius [px], growth [px/s]
        self.color, self.alpha = color, alpha
        self.gravity, self.drag = gravity, drag  # [m/s^2], [1/s]


class ParticleSystem:
    MAX_PARTICLES = 400

    def __init__(self):
        self.items = []

    def _add(self, *args):
        if len(self.items) >= self.MAX_PARTICLES:
            self.items.pop(0)
        self.items.append(Particle(*args))

    def dust(self, x_m, y_m, count, spread=1.0, bias_vx=0.0):
        """Soft puffs kicked up from the ground."""
        for _ in range(count):
            self._add(
                x_m + random.uniform(-0.15, 0.15), y_m - random.uniform(0.0, 0.05),
                random.uniform(-spread, spread) + bias_vx, -random.uniform(0.1, 0.6),
                random.uniform(0.35, 0.8), random.uniform(2.0, 4.0), random.uniform(6.0, 14.0),
                COLOR_DUST, 150, -0.4, 3.0,
            )

    def sparkle(self, x_m, y_m, count=16):
        """Burst of light when an orb is collected."""
        for _ in range(count):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(0.8, 3.2)
            self._add(
                x_m, y_m, math.cos(angle) * speed, math.sin(angle) * speed,
                random.uniform(0.35, 0.7), random.uniform(1.5, 3.2), -2.0,
                random.choice((COLOR_ORB_CORE, COLOR_ORB, COLOR_TEXT)), 235, 3.0, 2.0,
            )

    def gore(self, x_m, y_m, count, direction):
        """Splatter of green/red goo thrown in `direction` (+1 right, -1 left)."""
        for _ in range(count):
            self._add(
                x_m, y_m,
                direction * random.uniform(0.5, 4.0) + random.uniform(-1.0, 1.0),
                -random.uniform(0.3, 3.5),
                random.uniform(0.35, 0.8), random.uniform(1.8, 3.4), -2.2,
                random.choice(GORE_COLORS), 240, 9.0, 1.2,
            )

    def muzzle(self, x_m, y_m, angle):
        """Short yellow flash at the muzzle of a gun."""
        for _ in range(5):
            a = angle + random.uniform(-0.35, 0.35)
            speed = random.uniform(2.0, 6.0)
            self._add(
                x_m, y_m, math.cos(a) * speed, math.sin(a) * speed,
                random.uniform(0.06, 0.14), random.uniform(1.8, 3.0), -6.0,
                random.choice((COLOR_BULLET, COLOR_FIRE)), 255, 0.0, 4.0,
            )

    def smoke(self, x_m, y_m):
        """One puff of rocket exhaust."""
        self._add(
            x_m, y_m, random.uniform(-0.3, 0.3), random.uniform(-0.3, 0.1),
            random.uniform(0.35, 0.6), random.uniform(2.0, 3.0), 7.0,
            random.choice((COLOR_SMOKE, COLOR_FIRE)), 150, -0.3, 2.0,
        )

    def explosion(self, x_m, y_m):
        """Fireball + smoke of a rocket explosion."""
        for _ in range(46):
            a = random.uniform(0.0, math.tau)
            speed = random.uniform(1.0, 8.0)
            self._add(
                x_m, y_m, math.cos(a) * speed, math.sin(a) * speed,
                random.uniform(0.3, 0.75), random.uniform(3.0, 7.0), -4.0,
                random.choice((COLOR_FIRE, COLOR_FIRE_CORE, COLOR_ROCKET_TIP)), 240, 1.0, 2.5,
            )
        for _ in range(16):
            a = random.uniform(0.0, math.tau)
            speed = random.uniform(0.5, 3.0)
            self._add(
                x_m, y_m, math.cos(a) * speed, math.sin(a) * speed - 0.5,
                random.uniform(0.8, 1.5), random.uniform(6.0, 10.0), 12.0,
                COLOR_METAL_DARK, 150, -1.0, 1.5,
            )

    def update(self, dt):
        alive = []
        for p in self.items:
            p.life -= dt
            if p.life <= 0.0:
                continue
            damp = math.exp(-p.drag * dt)
            p.vx *= damp
            p.vy = p.vy * damp + p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.y > GROUND_LEVEL_M and p.gravity > 0.0:  # goo splats on the floor, not under it
                p.y = GROUND_LEVEL_M
                p.vy = 0.0
                p.vx *= 0.3
            p.size += p.grow * dt
            alive.append(p)
        self.items = alive

    def draw(self, surface, layer, camera_x):
        """Draw into a transparent layer, then blit only the touched rectangle."""
        if not self.items:
            return
        min_x = min_y = 10 ** 9
        max_x = max_y = -10 ** 9
        for p in self.items:
            sx = int(p.x * PIXELS_PER_METER - camera_x)
            sy = int(p.y * PIXELS_PER_METER)
            if sx < -30 or sx > WINDOW_WIDTH + 30:
                continue
            radius = max(1, int(p.size))
            alpha = int(p.alpha * (p.life / p.max_life))
            pygame.draw.circle(layer, (*p.color, alpha), (sx, sy), radius)
            min_x, max_x = min(min_x, sx - radius), max(max_x, sx + radius)
            min_y, max_y = min(min_y, sy - radius), max(max_y, sy + radius)
        if max_x < min_x:
            return
        dirty = pygame.Rect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1).clip(
            layer.get_rect())
        surface.blit(layer, dirty, dirty)
        layer.fill((0, 0, 0, 0), dirty)


# =============================================================================
# 4. COLLECTIBLE ORBS (generated procedurally, same every run)
# =============================================================================

@functools.lru_cache(maxsize=512)  # cells never change, so compute each one only once
def orbs_in_cell(cell):
    """Orbs of one world cell: (((cell, i), x_m, height_above_ground_m), ...)."""
    kind = hash01(cell, 11)
    if cell == 0 or kind < 0.30:  # keep the spawn area clear; ~30% of cells are empty
        return ()
    x0 = cell * ORB_CELL_M + 1.0 + hash01(cell, 12) * 2.0
    orbs = []
    if kind < 0.75:
        # A jump arc: run under the ends, leap for the top
        for i in range(5):
            u = i / 4.0
            orbs.append(((cell, i), x0 + i * 1.0, 0.75 + 1.25 * 4.0 * u * (1.0 - u)))
    else:
        # A low trail you simply run through
        for i in range(4):
            orbs.append(((cell, i), x0 + i * 0.9, 0.55))
    return tuple(orbs)


def collect_orbs(player, collected, ground_level_m):
    """Pick up orbs close to the centre of mass; returns [(x_m, y_m), ...] of new pickups."""
    picked = []
    cell = math.floor(player.position.x / ORB_CELL_M)
    for c in (cell - 1, cell, cell + 1):
        for orb_id, x_m, h_m in orbs_in_cell(c):
            if orb_id in collected:
                continue
            y_m = ground_level_m - h_m
            if math.hypot(x_m - player.position.x, y_m - player.position.y) < ORB_PICKUP_RADIUS_M:
                collected.add(orb_id)
                picked.append((x_m, y_m))
    return picked


# =============================================================================
# 6. SCENERY (sky, parallax layers, ground, fireflies, orbs)
# =============================================================================

# (parallax, base height, ridge amplitude, ridge freq, hill amplitude, hill freq, phase)
MOUNTAIN_LAYERS = (
    (0.05, 230, 130, 0.0040, 24, 0.013, 0.3),
    (0.10, 150, 80, 0.0058, 18, 0.017, 2.1),
    (0.18, 90, 45, 0.0085, 12, 0.021, 4.2),
)


def draw_pine(surface, x, base_y, height, color):
    """A pine-tree silhouette: trunk plus three stacked triangles."""
    trunk_w = max(3, int(height * 0.06))
    pygame.draw.rect(surface, color,
                     (x - trunk_w / 2, base_y - height * 0.18, trunk_w, height * 0.18))
    for k in range(3):
        bottom = base_y - height * (0.15 + 0.25 * k)
        half = height * 0.23 * (1.0 - 0.22 * k)
        top = bottom - height * 0.40
        pygame.draw.polygon(surface, color, [(x - half, bottom), (x + half, bottom), (x, top)])


class Scenery:
    """
    Everything behind and around the runner. Static art is pre-rendered once;
    every frame only blits it at the right parallax offset.

    Layers (parallax factor = fraction of the camera speed):
      stars 1% | moon fixed | clouds ~5% | far mountains 5% | mid mountains 10%
      fog | near hills 18% | back trees 34% | front trees 58% | ground 100%
    """

    def __init__(self, ground_level_m):
        self.ground_px = int(ground_level_m * PIXELS_PER_METER)
        rng = random.Random(7)

        self.moon, self.moon_pos, self.moon_glow, self.moon_glow_pos = self._build_moon()
        self.sky = self._build_sky()
        # The moon and its glow never move, so they are baked into the sky image once
        self.sky.blit(self.moon_glow, self.moon_glow_pos, special_flags=pygame.BLEND_RGB_ADD)
        self.sky.blit(self.moon, self.moon_pos)
        self.ground = self._build_ground()
        self.fog = self._build_fog()

        # Per-frame work that only depends on the world position is memoised here
        self._ridge_cache = [{}, {}, {}]  # mountain heights per layer
        self._blade_cache = {}  # grass blade shapes
        self._label_cache = {}  # "5 m", "10 m", ... distance labels

        self.grid_minor = pygame.Surface((1, self.ground_px), pygame.SRCALPHA)
        self.grid_minor.fill((148, 163, 184, 16))
        self.grid_minor = self.grid_minor.convert_alpha()
        self.grid_major = pygame.Surface((2, self.ground_px), pygame.SRCALPHA)
        self.grid_major.fill((148, 163, 184, 46))
        self.grid_major = self.grid_major.convert_alpha()

        # Stars: x, y, size, twinkle phase, twinkle speed, brightness
        self.stars = [
            (rng.uniform(0, WINDOW_WIDTH), rng.uniform(0, self.ground_px * 0.62),
             rng.choice((1, 1, 1, 2)), rng.uniform(0, math.tau), rng.uniform(0.8, 2.5),
             rng.uniform(110, 255))
            for _ in range(150)
        ]
        # Keep the stars off the (pre-rendered) moon disc
        self.stars = [s for s in self.stars if (s[0] - 940) ** 2 + (s[1] - 105) ** 2 > 42 ** 2]

        # Clouds drift on their own and also slide with a tiny parallax
        self.cloud_sprites = [self._build_cloud(rng, w, h) for w, h in
                              ((300, 84), (240, 66), (360, 96), (200, 56))]
        self.cloud_span = WINDOW_WIDTH + 700
        self.clouds = [
            (i * self.cloud_span / 7 + rng.uniform(-60, 60), rng.uniform(36, 210),
             i % len(self.cloud_sprites), rng.uniform(4, 12), rng.uniform(0.04, 0.09))
            for i in range(7)
        ]

        # Fireflies: x, height above ground, wander x/y, wander speeds, phase, pulse speed
        self.fireflies = [
            (rng.uniform(0, WINDOW_WIDTH + 400), rng.uniform(30, 210), rng.uniform(10, 40),
             rng.uniform(6, 22), rng.uniform(0.3, 0.9), rng.uniform(0.4, 1.1),
             rng.uniform(0, math.tau), rng.uniform(1.5, 3.5))
            for _ in range(22)
        ]
        self.firefly_glows = [make_glow(16, COLOR_FIREFLY, s) for s in
                              (0.2, 0.35, 0.5, 0.7, 0.85, 1.0)]
        self.orb_glows = [make_glow(30, COLOR_ORB, s) for s in (0.5, 0.65, 0.8, 1.0)]

    # ------------------------------------------------------------------ build

    def _build_sky(self):
        sky = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
        sky.fill(COLOR_GROUND)
        for y in range(self.ground_px + 1):
            t = (y / self.ground_px) ** 1.7  # glow concentrates near the horizon
            pygame.draw.line(sky, lerp_color(COLOR_SKY_TOP, COLOR_SKY_HORIZON, t), (0, y),
                             (WINDOW_WIDTH, y))
        return sky.convert()

    def _build_ground(self):
        height = WINDOW_HEIGHT - self.ground_px
        ground = pygame.Surface((WINDOW_WIDTH, height))
        for y in range(height):
            pygame.draw.line(ground,
                             lerp_color(COLOR_GROUND_TOP, COLOR_GROUND, (y / height) ** 0.7),
                             (0, y), (WINDOW_WIDTH, y))
        return ground.convert()

    def _build_fog(self):
        height = 220
        fog = pygame.Surface((WINDOW_WIDTH, height), pygame.SRCALPHA)
        for y in range(height):
            alpha = int(120 * (y / height) ** 1.6)
            pygame.draw.line(fog, (*COLOR_FOG, alpha), (0, y), (WINDOW_WIDTH, y))
        return fog.convert_alpha()  # same pixel format as the screen -> much faster blits

    def _build_moon(self):
        radius = 34
        centre = (940, 105)
        moon = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        mc = (radius + 1, radius + 1)
        pygame.draw.circle(moon, COLOR_MOON, mc, radius)
        for dx, dy, cr in ((-10, -8, 8), (9, 6, 6), (-4, 14, 5), (14, -12, 4), (-18, 8, 3)):
            pygame.draw.circle(moon, COLOR_MOON_CRATER, (mc[0] + dx, mc[1] + dy), cr)
        glow_r = 200
        glow = make_glow(glow_r, (70, 90, 170), 0.55)
        return (moon, (centre[0] - radius - 1, centre[1] - radius - 1),
                glow, (centre[0] - glow_r, centre[1] - glow_r))

    def _build_cloud(self, rng, width, height):
        """Soft cloud: nested translucent ellipses drawn small, then smooth-scaled up."""
        sw, sh = width // 2, height // 2
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        n = rng.randint(5, 8)
        puffs = []
        for k in range(n):
            u = k / (n - 1)
            puffs.append((sw * (0.14 + 0.72 * u) + rng.uniform(-4, 4),
                          sh * (0.68 - 0.24 * math.sin(math.pi * u)),
                          sw * rng.uniform(0.14, 0.24), sh * rng.uniform(0.28, 0.44)))
        for scale, alpha in ((1.0, 14), (0.86, 20), (0.72, 26), (0.58, 32), (0.44, 38), (0.30, 44)):
            for cx, cy, rw, rh in puffs:
                rect = pygame.Rect(0, 0, max(2, int(rw * 2 * scale)), max(2, int(rh * 2 * scale)))
                rect.center = (int(cx), int(cy))
                pygame.draw.ellipse(small, (*COLOR_CLOUD, alpha), rect)
        return pygame.transform.smoothscale(small, (width, height)).convert_alpha()

    # ------------------------------------------------------------------- draw

    def draw_background(self, surface, camera_x, t):
        gp = self.ground_px
        surface.blit(self.sky, (0, 0))

        # Stars (twinkling, almost no parallax)
        for x, y, size, phase, speed, bright in self.stars:
            b = bright * (0.65 + 0.35 * math.sin(t * speed + phase))
            surface.fill((int(b * 0.88), int(b * 0.92), int(b)),
                         (int((x - camera_x * 0.01) % WINDOW_WIDTH), int(y), size, size))

        # (the moon and its glow are already part of the sky image)

        # Clouds
        for x0, y, sprite, drift, parallax in self.clouds:
            sx = (x0 + t * drift - camera_x * parallax) % self.cloud_span - 350
            surface.blit(self.cloud_sprites[sprite], (int(sx), int(y)))

        # Mountains (far, mid), fog, then nearer layers
        self._draw_mountains(surface, camera_x, 0)
        self._draw_mountains(surface, camera_x, 1)
        surface.blit(self.fog, (0, gp - self.fog.get_height()))
        self._draw_mountains(surface, camera_x, 2)

        self._draw_trees(surface, camera_x, 0.34, 130, COLOR_TREES_BACK, 90, 140, 100)
        self._draw_trees(surface, camera_x, 0.58, 210, COLOR_TREES_FRONT, 150, 230, 200)

    def _mountain_height(self, layer, idx):
        """Height of a mountain layer at world sample `idx` (computed once, then cached)."""
        cache = self._ridge_cache[layer]
        h = cache.get(idx)
        if h is None:
            if len(cache) > 3000:
                cache.clear()
            _, base, r_amp, r_freq, h_amp, h_freq, phase = MOUNTAIN_LAYERS[layer]
            x = idx * 8
            ridge = 1.0 - abs(math.sin(x * r_freq + phase))  # sharp peaks
            hill = 0.5 * math.sin(x * h_freq + phase * 1.7) + 0.5 * math.sin(
                x * h_freq * 2.3 + phase)
            h = cache[idx] = base + r_amp * ridge + h_amp * hill
        return h

    def _draw_mountains(self, surface, camera_x, layer):
        offset = camera_x * MOUNTAIN_LAYERS[layer][0]
        gp = self.ground_px
        first = math.floor(offset / 8) - 1
        last = math.floor((offset + WINDOW_WIDTH) / 8) + 3
        points = [(first * 8 - offset, gp)]
        for idx in range(first, last + 1):
            points.append((idx * 8 - offset, gp - self._mountain_height(layer, idx)))
        points.append((last * 8 - offset, gp))
        pygame.draw.polygon(surface, COLOR_MOUNTAINS[layer], points)

    def _draw_trees(self, surface, camera_x, parallax, cell_w, color, h_min, h_max, salt):
        offset = camera_x * parallax
        first = math.floor(offset / cell_w) - 1
        last = math.floor((offset + WINDOW_WIDTH) / cell_w) + 1
        for i in range(first, last + 1):
            if hash01(i, salt) < 0.18:  # leave some gaps
                continue
            x = i * cell_w + hash01(i, salt + 1) * cell_w * 0.7 - offset
            height = h_min + hash01(i, salt + 2) * (h_max - h_min)
            draw_pine(surface, x, self.ground_px, height, color)

    def draw_ground(self, surface, camera_x, t, label_font, player, show_grid):
        gp = self.ground_px
        surface.blit(self.ground, (0, gp))
        self._draw_pebbles(surface, camera_x)

        # Metre grid: faint lines in the "measurement plane"
        first_m = int(camera_x // PIXELS_PER_METER) - 1
        last_m = int((camera_x + WINDOW_WIDTH) // PIXELS_PER_METER) + 2
        majors = []
        for m in range(first_m, last_m):
            px = int(m * PIXELS_PER_METER - camera_x)
            if m % 5 == 0:
                majors.append((m, px))
                if show_grid:
                    surface.blit(self.grid_major, (px - 1, 0))
            elif show_grid:
                surface.blit(self.grid_minor, (px, 0))

        pygame.draw.line(surface, COLOR_GROUND_LINE, (0, gp), (WINDOW_WIDTH, gp), 4)

        height_above_ground = max(0.0, GROUND_LEVEL_M - (player.position.y + player.height_m / 2.0))
        self._draw_grass(surface, camera_x, t, player.position.x * PIXELS_PER_METER,
                         height_above_ground)

        # Distance markers every 5 m
        for m, px in majors:
            label = self._label_cache.get(m)
            if label is None:
                if len(self._label_cache) > 200:
                    self._label_cache.clear()
                label = self._label_cache[m] = label_font.render(f"{m} m", True, COLOR_LABEL)
            surface.blit(label, (px + 4, gp + 8))
            pygame.draw.circle(surface, COLOR_MARKER, (px, gp), 4)

    def _draw_pebbles(self, surface, camera_x):
        cell = 90
        first = int(camera_x // cell) - 1
        last = int((camera_x + WINDOW_WIDTH) // cell) + 2
        span = WINDOW_HEIGHT - self.ground_px - 70
        for i in range(first, last):
            if hash01(i, 41) > 0.55:
                continue
            x = i * cell + hash01(i, 42) * cell - camera_x
            y = self.ground_px + 30 + hash01(i, 43) * span
            w = 5 + hash01(i, 44) * 12
            pygame.draw.ellipse(surface, COLOR_PEBBLE, (x - w / 2, y - w * 0.22, w, w * 0.45))

    def _draw_grass(self, surface, camera_x, t, player_px, player_height_m):
        """Blades sway in the wind and bend away from the runner's feet."""
        gp = self.ground_px
        step = 6
        first = int(camera_x // step) - 1
        last = int((camera_x + WINDOW_WIDTH) // step) + 2
        blades = self._blade_cache
        if len(blades) > 3000:
            blades.clear()
        for i in range(first, last):
            blade = blades.get(i)
            if blade is None:
                r = hash01(i, 31)
                h = 4 + r * 8
                if hash01(i, 32) > 0.82:  # occasional tall tuft
                    h += 8 + 8 * hash01(i, 33)
                blade = blades[i] = (h, COLOR_GRASS_A if r < 0.5 else COLOR_GRASS_B,
                                     2 if h > 12 else 1, hash01(i, 34) > 0.985)
            h, color, width, flower = blade
            world_x = i * step
            sway = math.sin(t * 1.7 + world_x * 0.035) * 0.22 * h
            dx = world_x - player_px
            if abs(dx) < 50 and player_height_m < 0.5:
                push = (1.0 - abs(dx) / 50.0) * (1.0 if dx > 0 else -1.0)
                sway += push * h * 0.7 * (1.0 - player_height_m / 0.5)
            sx = world_x - camera_x
            tip = (sx + sway, gp - h)
            pygame.draw.line(surface, color, (sx, gp), tip, width)
            if flower:  # rare glowing flower
                pygame.draw.circle(surface, COLOR_ORB_CORE, (int(tip[0]), int(tip[1])), 3)

    def draw_orbs(self, surface, camera_x, ground_level_m, collected, t):
        first = math.floor(camera_x / PIXELS_PER_METER / ORB_CELL_M) - 1
        last = math.floor((camera_x + WINDOW_WIDTH) / PIXELS_PER_METER / ORB_CELL_M) + 1
        for cell in range(first, last + 1):
            for orb_id, x_m, h_m in orbs_in_cell(cell):
                if orb_id in collected:
                    continue
                sx = x_m * PIXELS_PER_METER - camera_x
                if sx < -40 or sx > WINDOW_WIDTH + 40:
                    continue
                sy = (ground_level_m - h_m) * PIXELS_PER_METER + math.sin(t * 3.0 + x_m * 1.7) * 4
                pulse = 0.5 + 0.5 * math.sin(t * 4.0 + x_m * 2.3)
                glow = self.orb_glows[int(pulse * (len(self.orb_glows) - 1) + 0.5)]
                r = glow.get_width() // 2
                surface.blit(glow, (int(sx) - r, int(sy) - r), special_flags=pygame.BLEND_RGB_ADD)
                # Crystal that appears to spin (its width oscillates)
                w = 2 + 7 * abs(math.cos(t * 2.5 + x_m))
                points = [(sx, sy - 9), (sx + w, sy), (sx, sy + 9), (sx - w, sy)]
                pygame.draw.polygon(surface, COLOR_ORB_CORE, points)
                pygame.draw.polygon(surface, (250, 245, 255), points, 1)

    def draw_fireflies(self, surface, camera_x, t):
        span = WINDOW_WIDTH + 400
        for x0, h0, ax, ay, fx, fy, phase, pulse_speed in self.fireflies:
            sx = (x0 + math.sin(t * fx + phase) * ax - camera_x * 0.85) % span - 200
            sy = self.ground_px - h0 + math.sin(t * fy + phase * 1.3) * ay
            pulse = 0.5 + 0.5 * math.sin(t * pulse_speed + phase * 2.0)
            glow = self.firefly_glows[int(pulse * (len(self.firefly_glows) - 1) + 0.5)]
            r = glow.get_width() // 2
            surface.blit(glow, (int(sx) - r, int(sy) - r), special_flags=pygame.BLEND_RGB_ADD)
            if pulse > 0.35:
                surface.fill((255, 255, 210), (int(sx), int(sy), 2, 2))


# =============================================================================
# 7. HUD (telemetry panel, counters, hearts)
# =============================================================================

class TextCache:
    """Rendering text is slow, so each distinct string is rendered only once."""

    def __init__(self):
        self._cache = {}

    def get(self, font, text, color):
        key = (id(font), text, color)
        surf = self._cache.get(key)
        if surf is None:
            if len(self._cache) > 300:
                self._cache.clear()
            surf = self._cache[key] = font.render(text, True, color)
        return surf


class TelemetryPanel:
    """Fixed on-screen dashboard with the live physics values.

    Text rendering is the slowest part of a HUD, so the panel is redrawn only
    ~10 times per second and the cached image is blitted on the other frames."""

    WIDTH = 440
    LINE_H = 23
    REFRESH_S = 0.1

    def __init__(self, font):
        self.font = font
        self.surface = None
        self.timer = 0.0

    def draw(self, surface, dt, player, dt_ms, ground_level_m, orbs, kills, zombies_alive):
        self.timer -= dt
        if self.surface is None or self.timer <= 0.0:
            self.timer = self.REFRESH_S
            self._redraw(player, dt_ms, ground_level_m, orbs, kills, zombies_alive)
        surface.blit(self.surface, (20, 20))

    def _redraw(self, player, dt_ms, ground_level_m, orbs, kills, zombies_alive):
        speed = player.velocity.length()
        accel = player.acceleration.length()
        kinetic_energy = 0.5 * player.mass * speed ** 2
        height_above_ground = ground_level_m - (player.position.y + player.height_m / 2.0)

        # Vertical values are shown with "up = positive"
        lines = [
            (tr("tel.title"), COLOR_VELOCITY),
            (tr("tel.mass", v=player.mass), COLOR_TEXT),
            (tr("tel.frame", v=dt_ms), COLOR_TEXT),
            (tr("tel.pos", v=player.position.x), COLOR_TEXT),
            (tr("tel.height", v=height_above_ground), COLOR_TEXT),
            (tr("tel.vx", v=player.velocity.x, kmh=player.velocity.x * 3.6), COLOR_TEXT),
            (tr("tel.vy", v=-player.velocity.y), COLOR_TEXT),
            (tr("tel.speed", v=speed), COLOR_TEXT),
            (tr("tel.ax", v=player.acceleration.x), COLOR_TEXT),
            (tr("tel.ay", v=-player.acceleration.y), COLOR_TEXT),
            (tr("tel.a", v=accel), COLOR_TEXT),
            (tr("tel.force", v=player.net_force.x), COLOR_TEXT),
            (tr("tel.energy", v=kinetic_energy), COLOR_TEXT),
            (tr("tel.impact", v=player.last_impact), COLOR_TEXT),
            (tr("tel.orbs", n=orbs), COLOR_ORB_CORE),
            (tr("tel.kills", k=kills, a=zombies_alive), COLOR_BAD),
            (
                tr("tel.ground") if player.on_ground else tr("tel.air"),
                COLOR_GOOD if player.on_ground else COLOR_BAD,
            ),
        ]

        if self.surface is None:
            panel_h = 20 + len(lines) * self.LINE_H + 10
            self.surface = pygame.Surface((self.WIDTH, panel_h), pygame.SRCALPHA).convert_alpha()
        self.surface.fill((15, 23, 42, 230))
        pygame.draw.rect(self.surface, COLOR_GRID_MAJOR, self.surface.get_rect(), width=1)
        y = 10
        for text, color in lines:
            self.surface.blit(self.font.render(text, True, color), (15, y))
            y += self.LINE_H


def draw_heart(surface, cx, cy, color):
    pygame.draw.circle(surface, color, (cx - 4, cy - 3), 5)
    pygame.draw.circle(surface, color, (cx + 4, cy - 3), 5)
    pygame.draw.polygon(surface, color, [(cx - 8, cy - 1), (cx + 8, cy - 1), (cx, cy + 9)])


def draw_skull(surface, cx, cy, s, color):
    r = int(10 * s)
    pygame.draw.circle(surface, color, (cx, cy - 2), r)
    pygame.draw.rect(surface, color, (cx - r // 2, cy + r // 2 - 3, r, r // 2 + 3), border_radius=2)
    eye = max(2, int(3 * s))
    pygame.draw.circle(surface, (15, 23, 42), (cx - r // 3, cy - 3), eye)
    pygame.draw.circle(surface, (15, 23, 42), (cx + r // 3, cy - 3), eye)


def draw_counters(surface, font, texts, orbs, kills, orb_flash, kill_flash):
    """Orb counter (left of centre) and zombie kill counter (right of centre)."""
    cy = 36

    label = texts.get(font, str(orbs), COLOR_ORB_CORE if orb_flash > 0.0 else COLOR_TEXT)
    x = WINDOW_WIDTH // 2 - 70 - (26 + label.get_width()) // 2
    s = 1.0 + 0.5 * clamp(orb_flash / 0.4, 0.0, 1.0)  # icon pops when you pick one up
    diamond = [(x + 9, cy - 11 * s), (x + 9 + 8 * s, cy), (x + 9, cy + 11 * s), (x + 9 - 8 * s, cy)]
    pygame.draw.polygon(surface, COLOR_ORB, diamond)
    pygame.draw.polygon(surface, COLOR_ORB_CORE, diamond, 2)
    surface.blit(label, (x + 26, cy - label.get_height() // 2))

    label = texts.get(font, str(kills), COLOR_BAD if kill_flash > 0.0 else COLOR_TEXT)
    x = WINDOW_WIDTH // 2 + 70 - (26 + label.get_width()) // 2
    s = 1.0 + 0.4 * clamp(kill_flash / 0.4, 0.0, 1.0)  # skull pops on a kill
    draw_skull(surface, x + 10, cy, s, COLOR_BONE)
    surface.blit(label, (x + 26, cy - label.get_height() // 2))


def draw_hearts(surface, hp, max_hp):
    spacing = 26
    x0 = WINDOW_WIDTH // 2 - (max_hp - 1) * spacing // 2
    for i in range(max_hp):
        draw_heart(surface, x0 + i * spacing, 78, COLOR_HEART if i < hp else COLOR_HEART_EMPTY)


def build_hurt_vignette():
    """Red frame around the screen, shown for a moment when a zombie bites."""
    surf = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    steps = 36
    for i in range(steps):
        alpha = int(130 * (1.0 - i / steps) ** 2)
        pygame.draw.rect(surf, (200, 20, 30, alpha),
                         (i * 4, i * 4, WINDOW_WIDTH - i * 8, WINDOW_HEIGHT - i * 8), width=4)
    return surf.convert_alpha()


def build_dim_overlay():
    surf = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    surf.fill((6, 8, 20, 150))
    return surf.convert_alpha()


# =============================================================================
# 7b. MENUS, SHOP, WEAPON BAR, FULL SCREEN
# =============================================================================

SCALED_FLAG = getattr(pygame, "SCALED", 0)


def make_screen(fullscreen):
    """The game always draws on a 1200x700 canvas. SCALED stretches it to the monitor (black bars keep
    the proportions) and also converts the mouse position back to canvas coordinates for us."""
    flags = SCALED_FLAG | (pygame.FULLSCREEN if fullscreen else 0)
    return pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), flags)


SHOP_BUTTON = pygame.Rect(WINDOW_WIDTH - 20 - 184, 16, 184, 38)  # top-right corner
PAUSE_BUTTON = pygame.Rect(SHOP_BUTTON.left - 8 - 44, 16, 44, 38)


def button_column(count, top, w=320, h=46, gap=12):
    x = WINDOW_WIDTH // 2 - w // 2
    return [pygame.Rect(x, top + i * (h + gap), w, h) for i in range(count)]


MENU_PANEL = pygame.Rect(WINDOW_WIDTH // 2 - 200, 56, 400, 590)
PAUSE_KEYS = ("resume", "shop", "restart", "fullscreen", "title", "quit")
PAUSE_RECTS = button_column(len(PAUSE_KEYS), MENU_PANEL.top + 92)
TITLE_KEYS = ("story", "chapters", "free", "fullscreen", "quit")
TITLE_RECTS = button_column(len(TITLE_KEYS), 330)
WIN_KEYS = ("continue", "title")
WIN_RECTS = button_column(len(WIN_KEYS), 430)

# Language selector: a row of four buttons (one per language) in the title menu and in the pause menu
LANG_BTN_W, LANG_BTN_H, LANG_BTN_GAP = 118, 34, 10


def lang_rects(y):
    total = len(LANGUAGES) * LANG_BTN_W + (len(LANGUAGES) - 1) * LANG_BTN_GAP
    x0 = WINDOW_WIDTH // 2 - total // 2
    return [pygame.Rect(x0 + i * (LANG_BTN_W + LANG_BTN_GAP), y, LANG_BTN_W, LANG_BTN_H)
            for i in range(len(LANGUAGES))]


TITLE_LANG_RECTS = lang_rects(262)
PAUSE_LANG_RECTS = lang_rects(MENU_PANEL.top + 92 + len(PAUSE_KEYS) * 58 + 18)


def pick_language(pos, rects):
    for code, rect in zip(LANGUAGES, rects):
        if rect.collidepoint(pos):
            return code
    return None


def draw_language_row(surface, texts, fonts, mouse, rects):
    caption = texts.get(fonts["desc"], tr("menu.language"), COLOR_LABEL)
    surface.blit(caption, (WINDOW_WIDTH // 2 - caption.get_width() // 2, rects[0].top - 20))
    for code, rect in zip(LANGUAGES, rects):
        active = code == get_language()
        hover = rect.collidepoint(mouse)
        pygame.draw.rect(surface, COLOR_BUTTON_HOVER if (hover or active) else COLOR_BUTTON, rect,
                         border_radius=8)
        pygame.draw.rect(surface, COLOR_ACCENT if (hover or active) else COLOR_PANEL_EDGE, rect,
                         width=3 if active else 2, border_radius=8)
        label = texts.get(fonts["row"], LANGUAGE_NAMES[code],
                          COLOR_ACCENT if active else COLOR_TEXT)
        surface.blit(label, (rect.centerx - label.get_width() // 2,
                             rect.centery - label.get_height() // 2))


def fullscreen_label(fullscreen):
    return tr("menu.fullscreen", state_key="state.on" if fullscreen else "state.off")


def pause_labels(story_on, fullscreen):
    return (tr("menu.resume"), tr("menu.shop"),
            tr("menu.retry") if story_on else tr("menu.restart"),
            fullscreen_label(fullscreen), tr("menu.title"), tr("menu.quit"))


def title_labels(fullscreen):
    return (tr("menu.story"), tr("menu.chapters"), tr("menu.free"), fullscreen_label(fullscreen),
            tr("menu.quit"))


def win_labels():
    return (tr("win.continue"), tr("menu.title"))


def pick_button(pos, keys, rects):
    for key, rect in zip(keys, rects):
        if rect.collidepoint(pos):
            return key
    return None


SHOP_PANEL = pygame.Rect(130, 70, WINDOW_WIDTH - 260, 560)
SHOP_CLOSE = pygame.Rect(SHOP_PANEL.right - 48, SHOP_PANEL.top + 14, 34, 34)
SHOP_ROW_H = 58


def _shop_rows():
    """[(rect, kind, key), ...] - every clickable row of the shop (weapons on the left, upgrades on the right)."""
    gap = 24
    col_w = (SHOP_PANEL.width - 3 * gap) // 2
    left_x = SHOP_PANEL.left + gap
    right_x = left_x + col_w + gap
    top = SHOP_PANEL.top + 112
    rows = []
    for i, key in enumerate(WEAPON_ORDER):
        rows.append(
            (pygame.Rect(left_x, top + i * (SHOP_ROW_H + 8), col_w, SHOP_ROW_H), "weapon", key))
    for i, key in enumerate(UPGRADE_ORDER):
        rows.append(
            (pygame.Rect(right_x, top + i * (SHOP_ROW_H + 8), col_w, SHOP_ROW_H), "upgrade", key))
    return rows


SHOP_ROWS = _shop_rows()


# ------------------------------------------------------------------ shop logic

def shop_balance(player, orbs, kills):
    """Orbs available to spend: picked up + kills + story rewards - already spent."""
    return orbs + kills * KILL_REWARD + player.bonus - player.spent


def buy_weapon(player, key, balance):
    """Buy a weapon, or just equip it if it is already owned. Returns (message, ok)."""
    cfg = WEAPONS[key]
    name = weapon_name(key)
    if key in player.weapons_owned:
        player.equip(key)
        return tr("shop.msg.equip", name=name), True
    if balance < cfg["cost"]:
        return tr("shop.msg.need_weapon", name=name, n=cfg["cost"] - balance), False
    player.spent += cfg["cost"]
    player.weapons_owned.add(key)
    player.equip(key)
    return tr("shop.msg.bought", name=name), True


def upgrade_cost(player, key):
    """Price of the next level, or None if the upgrade is maxed out."""
    cfg = UPGRADES[key]
    if cfg.get("repeat"):
        return cfg["costs"][0]
    level = player.upgrades.get(key, 0)
    return cfg["costs"][level] if level < len(cfg["costs"]) else None


def buy_upgrade(player, key, balance):
    """Buy the next level of an upgrade. Returns (message, ok)."""
    name = upgrade_name(key)
    cost = upgrade_cost(player, key)
    if cost is None:
        return tr("shop.msg.maxed", name=name), False
    if key == "medkit" and player.hp >= player.max_hp:
        return tr("shop.msg.hp_full"), False
    if balance < cost:
        return tr("shop.msg.need", n=cost - balance), False
    player.spent += cost
    if key == "medkit":
        player.hp = min(player.max_hp, player.hp + SHOP_MEDKIT_HEAL)
    else:
        player.upgrades[key] = player.upgrades.get(key, 0) + 1
        player.apply_upgrades()
        if key == "heart":
            player.hp += 1
    return tr("shop.msg.bought", name=name), True


def shop_click(pos, player, balance):
    """Handle a click inside the shop. Returns (message, ok) or None if no row was hit."""
    for rect, kind, key in SHOP_ROWS:
        if rect.collidepoint(pos):
            return buy_weapon(player, key, balance) if kind == "weapon" else buy_upgrade(player,
                                                                                         key,
                                                                                         balance)
    return None


# ------------------------------------------------------------------ drawing helpers

def draw_orb(surface, cx, cy, s=1.0):
    """The little purple diamond that stands for an orb / for money."""
    diamond = [(cx, cy - 10 * s), (cx + 7 * s, cy), (cx, cy + 10 * s), (cx - 7 * s, cy)]
    pygame.draw.polygon(surface, COLOR_ORB, diamond)
    pygame.draw.polygon(surface, COLOR_ORB_CORE, diamond, 2)


def draw_price(surface, texts, font, right_x, cy, amount, affordable):
    label = texts.get(font, str(amount), COLOR_ORB_CORE if affordable else COLOR_BAD)
    x = right_x - label.get_width()
    surface.blit(label, (x, cy - label.get_height() // 2))
    draw_orb(surface, x - 14, cy, 0.9)


def draw_button(surface, texts, font, rect, label, hover, enabled=True):
    hot = hover and enabled
    pygame.draw.rect(surface, COLOR_BUTTON_HOVER if hot else COLOR_BUTTON, rect, border_radius=8)
    pygame.draw.rect(surface, COLOR_ACCENT if hot else COLOR_PANEL_EDGE, rect, width=2,
                     border_radius=8)
    text = texts.get(font, label, COLOR_TEXT if enabled else COLOR_LABEL)
    surface.blit(text,
                 (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))


def draw_buttons(surface, texts, font, keys, labels, rects, mouse, disabled=()):
    for key, label, rect in zip(keys, labels, rects):
        draw_button(surface, texts, font, rect, label, rect.collidepoint(mouse),
                    enabled=key not in disabled)


def draw_upgrade_icon(surface, key, cx, cy):
    if key == "medkit":
        pygame.draw.rect(surface, COLOR_TEXT, (cx - 13, cy - 10, 26, 20), border_radius=4)
        pygame.draw.rect(surface, COLOR_BAD, (cx - 2, cy - 7, 4, 14))
        pygame.draw.rect(surface, COLOR_BAD, (cx - 7, cy - 2, 14, 4))
    elif key == "heart":
        draw_heart(surface, cx, cy - 2, COLOR_HEART)
    elif key == "damage":
        pygame.draw.rect(surface, COLOR_FIRE, (cx - 12, cy - 5, 13, 10), border_radius=2)
        pygame.draw.polygon(surface, COLOR_BULLET,
                            [(cx + 1, cy - 5), (cx + 12, cy), (cx + 1, cy + 5)])
    elif key == "rate":
        pygame.draw.polygon(surface, COLOR_VELOCITY,
                            [(cx + 3, cy - 13), (cx - 8, cy + 2), (cx - 1, cy + 2),
                             (cx - 4, cy + 13), (cx + 8, cy - 3), (cx + 1, cy - 3)])
    elif key == "boots":
        for dx in (-7, 3):
            pygame.draw.lines(surface, COLOR_GOOD, False,
                              [(cx + dx - 4, cy - 9), (cx + dx + 4, cy), (cx + dx - 4, cy + 9)], 4)


def draw_top_buttons(surface, texts, font, mouse, shop_enabled):
    """Pause button and shop button in the top-right corner of the screen."""
    hover = PAUSE_BUTTON.collidepoint(mouse)
    pygame.draw.rect(surface, COLOR_BUTTON_HOVER if hover else COLOR_BUTTON, PAUSE_BUTTON,
                     border_radius=8)
    pygame.draw.rect(surface, COLOR_ACCENT if hover else COLOR_PANEL_EDGE, PAUSE_BUTTON, width=2,
                     border_radius=8)
    cx, cy = PAUSE_BUTTON.center
    pygame.draw.rect(surface, COLOR_TEXT, (cx - 8, cy - 8, 5, 16), border_radius=1)
    pygame.draw.rect(surface, COLOR_TEXT, (cx + 3, cy - 8, 5, 16), border_radius=1)

    hover = SHOP_BUTTON.collidepoint(mouse) and shop_enabled
    pygame.draw.rect(surface, COLOR_BUTTON_HOVER if hover else COLOR_BUTTON, SHOP_BUTTON,
                     border_radius=8)
    pygame.draw.rect(surface, COLOR_ACCENT if hover else COLOR_PANEL_EDGE, SHOP_BUTTON, width=2,
                     border_radius=8)
    draw_orb(surface, SHOP_BUTTON.left + 22, SHOP_BUTTON.centery, 1.0)
    label = texts.get(font, tr("shop.button"), COLOR_TEXT if shop_enabled else COLOR_LABEL)
    surface.blit(label, (SHOP_BUTTON.left + 42, SHOP_BUTTON.centery - label.get_height() // 2))


def draw_weapon_bar(surface, texts, font, player):
    """Four weapon slots under the hearts: the equipped one is highlighted, locked ones show a padlock."""
    slot_w, slot_h, gap = 52, 34, 8
    x0 = WINDOW_WIDTH // 2 - (len(WEAPON_ORDER) * slot_w + (len(WEAPON_ORDER) - 1) * gap) // 2
    for i, key in enumerate(WEAPON_ORDER):
        rect = pygame.Rect(x0 + i * (slot_w + gap), 100, slot_w, slot_h)
        owned = key in player.weapons_owned
        selected = player.weapon == key
        pygame.draw.rect(surface, COLOR_PANEL if owned else (10, 14, 26), rect, border_radius=6)
        pygame.draw.rect(surface, COLOR_ACCENT if selected else COLOR_PANEL_EDGE, rect,
                         width=2 if selected else 1, border_radius=6)
        if owned:
            draw_weapon_icon(surface, key, rect.centerx + 3, rect.centery + 1, 0.8)
        else:
            pygame.draw.rect(surface, COLOR_METAL_DARK, (rect.centerx - 6, rect.centery, 12, 9),
                             border_radius=2)
            pygame.draw.arc(surface, COLOR_METAL_DARK, (rect.centerx - 4, rect.centery - 8, 8, 12),
                            0, math.pi, 2)
        num = texts.get(font, str(i + 1), COLOR_ACCENT if selected else COLOR_LABEL)
        surface.blit(num, (rect.left + 4, rect.top + 1))


def draw_pause_menu(surface, texts, fonts, mouse, dim, labels, disabled=()):
    surface.blit(dim, (0, 0))
    pygame.draw.rect(surface, COLOR_PANEL, MENU_PANEL, border_radius=14)
    pygame.draw.rect(surface, COLOR_PANEL_EDGE, MENU_PANEL, width=2, border_radius=14)
    title = texts.get(fonts["title"], tr("pause.title"), COLOR_TEXT)
    surface.blit(title, (MENU_PANEL.centerx - title.get_width() // 2, MENU_PANEL.top + 24))
    draw_buttons(surface, texts, fonts["btn"], PAUSE_KEYS, labels, PAUSE_RECTS, mouse, disabled)
    draw_language_row(surface, texts, fonts, mouse, PAUSE_LANG_RECTS)
    hints = (tr("pause.hint1"), tr("pause.hint2"), tr("pause.hint3"))
    for i, line in enumerate(hints):
        text = texts.get(fonts["desc"], line, COLOR_LABEL)
        surface.blit(text,
                     (MENU_PANEL.centerx - text.get_width() // 2, MENU_PANEL.bottom - 88 + i * 22))


def draw_shop(surface, texts, fonts, mouse, dim, player, balance, message, message_ok):
    surface.blit(dim, (0, 0))
    pygame.draw.rect(surface, COLOR_PANEL, SHOP_PANEL, border_radius=14)
    pygame.draw.rect(surface, COLOR_PANEL_EDGE, SHOP_PANEL, width=2, border_radius=14)

    title = texts.get(fonts["title"], tr("shop.title"), COLOR_VELOCITY)
    surface.blit(title, (SHOP_PANEL.left + 24, SHOP_PANEL.top + 14))

    # Balance in the middle of the header
    amount = texts.get(fonts["row"], tr("shop.balance", n=balance), COLOR_TEXT)
    bx = SHOP_PANEL.centerx - (amount.get_width() + 30) // 2
    draw_orb(surface, bx + 8, SHOP_PANEL.top + 32, 1.2)
    surface.blit(amount, (bx + 28, SHOP_PANEL.top + 32 - amount.get_height() // 2))

    # Close button
    hover = SHOP_CLOSE.collidepoint(mouse)
    pygame.draw.rect(surface, COLOR_BUTTON_HOVER if hover else COLOR_BUTTON, SHOP_CLOSE,
                     border_radius=6)
    pygame.draw.rect(surface, COLOR_ACCENT if hover else COLOR_PANEL_EDGE, SHOP_CLOSE, width=2,
                     border_radius=6)
    cx, cy = SHOP_CLOSE.center
    pygame.draw.line(surface, COLOR_TEXT, (cx - 7, cy - 7), (cx + 7, cy + 7), 3)
    pygame.draw.line(surface, COLOR_TEXT, (cx - 7, cy + 7), (cx + 7, cy - 7), 3)

    # Column headers
    weapon_rows = [r for r in SHOP_ROWS if r[1] == "weapon"]
    upgrade_rows = [r for r in SHOP_ROWS if r[1] == "upgrade"]
    for rows, name in ((weapon_rows, tr("shop.weapons")), (upgrade_rows, tr("shop.upgrades"))):
        header = texts.get(fonts["desc"], name, COLOR_LABEL)
        surface.blit(header, (rows[0][0].left + 4, rows[0][0].top - 26))

    for rect, kind, key in SHOP_ROWS:
        hover = rect.collidepoint(mouse)
        equipped = kind == "weapon" and player.weapon == key
        pygame.draw.rect(surface, COLOR_BUTTON_HOVER if hover else COLOR_BUTTON, rect,
                         border_radius=8)
        pygame.draw.rect(surface,
                         COLOR_GOOD if equipped else (COLOR_ACCENT if hover else COLOR_PANEL_EDGE),
                         rect, width=2, border_radius=8)
        icon_x, mid_y = rect.left + 38, rect.centery
        right = rect.right - 14

        if kind == "weapon":
            cfg = WEAPONS[key]
            draw_weapon_icon(surface, key, icon_x, mid_y, 1.0)
            name = weapon_name(key)
            dmg = cfg["damage"] + player.upgrades.get("damage", 0)
            rate = 1.0 / (cfg["cooldown"] * player.cooldown_mult)
            desc = tr("shop.rowdesc", desc=weapon_desc(key), dmg=dmg, rate=rate)
            if equipped:
                status = texts.get(fonts["row"], tr("shop.equipped"), COLOR_GOOD)
                surface.blit(status, (right - status.get_width(), mid_y - status.get_height() // 2))
            elif key in player.weapons_owned:
                status = texts.get(fonts["row"], tr("shop.take"), COLOR_ACCENT)
                surface.blit(status, (right - status.get_width(), mid_y - status.get_height() // 2))
            else:
                draw_price(surface, texts, fonts["row"], right, mid_y, cfg["cost"],
                           balance >= cfg["cost"])
        else:
            cfg = UPGRADES[key]
            draw_upgrade_icon(surface, key, icon_x, mid_y)
            name, desc = upgrade_name(key), upgrade_desc(key)
            cost = upgrade_cost(player, key)
            if not cfg.get("repeat"):
                desc = f"{desc}  [{player.upgrades.get(key, 0)}/{len(cfg['costs'])}]"
            if cost is None:
                status = texts.get(fonts["row"], tr("shop.max"), COLOR_GOOD)
                surface.blit(status, (right - status.get_width(), mid_y - status.get_height() // 2))
            else:
                draw_price(surface, texts, fonts["row"], right, mid_y, cost, balance >= cost)

        surface.blit(texts.get(fonts["row"], name, COLOR_TEXT), (rect.left + 76, rect.top + 8))
        surface.blit(texts.get(fonts["desc"], desc, COLOR_LABEL), (rect.left + 76, rect.top + 33))

    left = weapon_rows[0][0].left + 4
    tip = texts.get(fonts["desc"], tr("shop.tip1"), COLOR_LABEL)
    surface.blit(tip, (left, weapon_rows[-1][0].bottom + 18))
    tip = texts.get(fonts["desc"], tr("shop.tip2", n=KILL_REWARD), COLOR_LABEL)
    surface.blit(tip, (left, weapon_rows[-1][0].bottom + 40))

    if message:
        note = texts.get(fonts["row"], message, COLOR_GOOD if message_ok else COLOR_BAD)
        surface.blit(note, (SHOP_PANEL.centerx - note.get_width() // 2, SHOP_PANEL.bottom - 46))
    close_hint = texts.get(fonts["desc"], tr("shop.close"), COLOR_LABEL)
    surface.blit(close_hint,
                 (SHOP_PANEL.centerx - close_hint.get_width() // 2, SHOP_PANEL.bottom - 24))


def draw_title(surface, texts, fonts, mouse, dim, fullscreen):
    surface.blit(dim, (0, 0))
    title = texts.get(fonts["huge"], tr("title.name"), COLOR_TEXT)
    surface.blit(title, (WINDOW_WIDTH // 2 - title.get_width() // 2, 120))
    sub = texts.get(fonts["row"], tr("title.sub"), COLOR_LABEL)
    surface.blit(sub, (WINDOW_WIDTH // 2 - sub.get_width() // 2, 205))
    draw_language_row(surface, texts, fonts, mouse, TITLE_LANG_RECTS)
    draw_buttons(surface, texts, fonts["btn"], TITLE_KEYS, title_labels(fullscreen), TITLE_RECTS,
                 mouse)
    hint = texts.get(fonts["desc"], tr("title.tip"), COLOR_LABEL)
    surface.blit(hint, (WINDOW_WIDTH // 2 - hint.get_width() // 2, TITLE_RECTS[-1].bottom + 26))


def draw_win(surface, texts, fonts, mouse, dim, kills, orbs, seconds):
    surface.blit(dim, (0, 0))
    title = texts.get(fonts["huge"], tr("win.title"), COLOR_GOOD)
    surface.blit(title, (WINDOW_WIDTH // 2 - title.get_width() // 2, 130))
    minutes, secs = divmod(int(seconds), 60)
    lines = (tr("win.kills", n=kills), tr("win.orbs", n=orbs), tr("win.time", m=minutes, s=secs))
    for i, line in enumerate(lines):
        text = texts.get(fonts["row"], line, COLOR_TEXT)
        surface.blit(text, (WINDOW_WIDTH // 2 - text.get_width() // 2, 250 + i * 36))
    draw_buttons(surface, texts, fonts["btn"], WIN_KEYS, win_labels(), WIN_RECTS, mouse)


# =============================================================================
# 7c. STORY: chapters, dialogues, radio messages, landmarks
# =============================================================================

# who -> (name shown in the dialogue box, colour)
SPEAKERS = {
    "narrator": ("who.narrator", COLOR_LABEL),
    "me": ("who.me", COLOR_TEXT),
    "vera": ("who.vera", COLOR_ACCENT),
    "warden": ("who.warden", COLOR_BAD),
    "butcher": ("who.butcher", COLOR_FIRE),
    "system": ("who.system", COLOR_VELOCITY),
    "loot": ("who.loot", COLOR_ORB_CORE),
}

TOAST_S = 6.5  # how long a radio message stays on the screen [s]
BANNER_S = 3.4  # how long a chapter title stays on the screen [s]
DEFAULT_SPAWN = (1.0, ZOMBIE_MAX_ALIVE,
                 ZOMBIE_WEIGHTS)  # (delay multiplier, max alive, kind weights)

# Everything the story does lives in this table - edit the distances / numbers freely.
# All the TEXTS are keys of the translation table _T (section 1b): the story is told in the current language.
#   start_x / goal_x : where the chapter starts (checkpoint) and where it ends [m]
#   weights / spawn_mul / max_alive : which zombies show up while running to the goal (spawn_mul < 1 = more often)
#   hints  : [(x, who, text)] radio messages that pop up (without stopping the game) when you pass x
#   intro / arrive / outro : dialogues [(who, text)] - at the start / at the goal / after the fight
#   event  : the fight at the goal - {"kind": "kills", "need": N, ...} or {"kind": "boss", "boss": kind, ...}
#   reward : orbs given at the end of the chapter
# To add a chapter: add a dict here, its texts to _T, and (if you want a new building) a landmark to draw_landmark().
CHAPTERS = (
    {
        "title": "c1.title",
        "start_x": 2.0, "goal_x": 90.0, "landmark": "station", "goal": "c1.goal",
        "weights": (("walker", 1.0),), "spawn_mul": 1.7, "max_alive": 4,
        "intro": (("narrator", "c1.i1"), ("me", "c1.i2"), ("vera", "c1.i3"), ("me", "c1.i4")),
        "hints": (
            (8.0, "system", "c1.h1"),
            (28.0, "system", "c1.h2"),
            (55.0, "system", "c1.h3"),
        ),
        "arrive": (("me", "c1.a1"), ("vera", "c1.a2")),
        "event": None,
        "reward": 10, "reward_text": "c1.reward",
        "outro": (),
    },
    {
        "title": "c2.title",
        "start_x": 90.0, "goal_x": 220.0, "landmark": "camp", "goal": "c2.goal",
        "weights": (("walker", 0.7), ("runner", 0.3)), "spawn_mul": 1.2, "max_alive": 6,
        "intro": (),
        "hints": ((140.0, "vera", "c2.h1"),),
        "arrive": (("narrator", "c2.a1"), ("vera", "c2.a2")),
        "event": {"kind": "kills", "need": 10, "max_alive": 6, "spawn_mul": 0.55,
                  "weights": (("walker", 0.6), ("runner", 0.4)), "text": "c2.event"},
        "reward": 15, "reward_text": "c2.reward",
        "outro": (("vera", "c2.o1"), ("me", "c2.o2")),
    },
    {
        "title": "c3.title",
        "start_x": 220.0, "goal_x": 380.0, "landmark": "bridge", "goal": "c3.goal",
        "weights": (("walker", 0.5), ("runner", 0.3), ("brute", 0.2)), "spawn_mul": 1.0,
        "max_alive": 7,
        "intro": (),
        "hints": ((290.0, "vera", "c3.h1"),),
        "arrive": (("narrator", "c3.a1"), ("vera", "c3.a2")),
        "event": {"kind": "kills", "need": 14, "max_alive": 7, "spawn_mul": 0.5,
                  "weights": (("walker", 0.35), ("runner", 0.3), ("brute", 0.35)),
                  "text": "c3.event"},
        "reward": 25, "reward_text": "c3.reward",
        "outro": (("vera", "c3.o1"),),
    },
    {  # NEW: the hospital - a bigger swarm, the weapon-switching hint
        "title": "c4.title",
        "start_x": 380.0, "goal_x": 540.0, "landmark": "hospital", "goal": "c4.goal",
        "weights": (("walker", 0.4), ("runner", 0.35), ("brute", 0.25)), "spawn_mul": 0.95,
        "max_alive": 7,
        "intro": (("vera", "c4.i1"), ("me", "c4.i2")),
        "hints": ((440.0, "system", "c4.h1"),),
        "arrive": (("narrator", "c4.a1"), ("vera", "c4.a2")),
        "event": {"kind": "kills", "need": 16, "max_alive": 7, "spawn_mul": 0.5,
                  "weights": (("walker", 0.4), ("runner", 0.35), ("brute", 0.25)),
                  "text": "c4.event"},
        "reward": 30, "reward_text": "c4.reward",
        "outro": (("vera", "c4.o1"), ("me", "c4.o2")),
    },
    {  # NEW: the rail tunnel - the first boss, the Butcher
        "title": "c5.title",
        "start_x": 540.0, "goal_x": 700.0, "landmark": "tunnel", "goal": "c5.goal",
        "weights": (("walker", 0.4), ("runner", 0.3), ("brute", 0.3)), "spawn_mul": 0.9,
        "max_alive": 7,
        "intro": (),
        "hints": ((600.0, "vera", "c5.h1"),),
        "arrive": (("narrator", "c5.a1"), ("vera", "c5.a2"), ("butcher", "c5.a3"), ("me", "c5.a4")),
        "event": {"kind": "boss", "boss": "butcher", "max_alive": 3, "spawn_mul": 1.6,
                  "weights": (("walker", 0.7), ("runner", 0.3)),
                  "text": "c5.event", "goal": "c5.evgoal"},
        "reward": 35, "reward_text": "c5.reward",
        "outro": (("narrator", "c5.o1"), ("vera", "c5.o2")),
    },
    {
        "title": "c6.title",
        "start_x": 700.0, "goal_x": 840.0, "landmark": "tower", "goal": "c6.goal",
        "weights": (("walker", 0.4), ("runner", 0.3), ("brute", 0.3)), "spawn_mul": 0.85,
        "max_alive": 7,
        "intro": (),
        "hints": ((770.0, "vera", "c6.h1"),),
        "arrive": (("vera", "c6.a1"), ("warden", "c6.a2"), ("me", "c6.a3")),
        "event": {"kind": "boss", "boss": "warden", "max_alive": 4, "spawn_mul": 1.4,
                  "weights": (("walker", 0.7), ("runner", 0.3)),
                  "text": "c6.event", "goal": "c6.evgoal"},
        "reward": 0, "reward_text": "",
        "outro": (("me", "c6.o1"), ("narrator", "c6.o2"), ("vera", "c6.o3"), ("narrator", "c6.o4")),
    },
)

TOWER_X_M = CHAPTERS[-1]["goal_x"]

# ------------------------------------------------------------------ chapter select (title menu -> "Select chapter")

CHAPTER_KEYS = tuple(range(len(CHAPTERS))) + ("back",)
CHAPTER_RECTS = button_column(len(CHAPTER_KEYS), 150, w=640)


def unlocked_chapters():
    """Index of the last chapter the player has reached (saved between runs)."""
    return min(SETTINGS["unlocked"], len(CHAPTERS) - 1)


def draw_chapters(surface, texts, fonts, mouse, dim):
    surface.blit(dim, (0, 0))
    title = texts.get(fonts["title"], tr("chapters.title"), COLOR_TEXT)
    surface.blit(title, (WINDOW_WIDTH // 2 - title.get_width() // 2, 70))
    unlocked = unlocked_chapters()
    labels = []
    for i, chapter in enumerate(CHAPTERS):
        name = tr(chapter["title"])
        labels.append(name if i <= unlocked else f"{name}   ({tr('chapters.locked')})")
    labels.append(tr("chapters.back"))
    draw_buttons(surface, texts, fonts["btn"], CHAPTER_KEYS, labels, CHAPTER_RECTS, mouse,
                 disabled=tuple(range(unlocked + 1, len(CHAPTERS))))
    hint = texts.get(fonts["desc"], tr("chapters.hint"), COLOR_LABEL)
    surface.blit(hint, (WINDOW_WIDTH // 2 - hint.get_width() // 2, CHAPTER_RECTS[-1].bottom + 22))


class Story:
    """The chapter state machine. It never draws and never touches the player: each call returns a list of
    "actions" (talk / toast / banner / reward / spawn_boss / victory) that main() carries out."""

    def __init__(self, chapter=0):
        self.chapter = chapter  # the chapter select can start the story later than chapter 1
        self.phase = "start"  # start | run | arrive | event | outro | free
        self.event_base = 0  # kill counter when the current fight began
        self.last_kills = 0
        self.hints_seen = set()
        self.talks_seen = set()

    @property
    def cfg(self):
        return CHAPTERS[self.chapter]

    @property
    def beacon_lit(self):
        return self.chapter == len(CHAPTERS) - 1 and self.phase in ("outro", "free")

    def _talk(self, key, lines):
        """A dialogue is told once; after a retry it is skipped."""
        mark = (self.chapter, key)
        if lines and mark not in self.talks_seen:
            self.talks_seen.add(mark)
            return [("talk", tuple(lines))]
        return None

    def begin(self):
        """Start (or restart) the whole story."""
        self.phase = "run"
        actions = [("banner", self.cfg["title"])]
        actions += self._talk("intro", self.cfg.get("intro")) or []
        return actions

    def retry(self):
        """The player died: back to the start of the chapter (no dialogue is repeated)."""
        self.phase = "run"
        return [("banner", self.cfg["title"])]

    def update(self, player_x, kills, boss_dead):
        self.last_kills = kills
        actions = []
        cfg = self.cfg
        if self.phase == "run":
            for i, (at, who, text) in enumerate(cfg.get("hints", ())):
                mark = (self.chapter, i)
                if mark not in self.hints_seen and player_x >= at:
                    self.hints_seen.add(mark)
                    actions.append(("toast", who, text))
            if player_x >= cfg["goal_x"]:
                self.phase = "arrive"
                actions += self._talk("arrive", cfg.get("arrive")) or self._start_event()
        elif self.phase == "event":
            ev = cfg["event"]
            done = boss_dead if ev["kind"] == "boss" else kills - self.event_base >= ev["need"]
            if done:
                self.phase = "outro"
                actions += self._outro()
        return actions

    def after_talk(self):
        """The dialogue box was closed: continue with whatever comes next."""
        if self.phase == "arrive":
            return self._start_event()
        if self.phase == "outro":
            return self._next_chapter()
        return []

    def _start_event(self):
        ev = self.cfg.get("event")
        if ev is None:
            self.phase = "outro"
            return self._outro()
        self.phase = "event"
        self.event_base = self.last_kills
        actions = [("banner", ev["text"])]
        if ev["kind"] == "boss":
            actions.append(("spawn_boss", ev["boss"]))
        return actions

    def _outro(self):
        cfg = self.cfg
        actions = []
        if cfg.get("reward"):
            actions.append(("reward", cfg["reward"], cfg.get("reward_text", "")))
        return actions + (self._talk("outro", cfg.get("outro")) or self._next_chapter())

    def _next_chapter(self):
        if self.chapter + 1 >= len(CHAPTERS):
            self.phase = "free"
            return [("victory",)]
        self.chapter += 1
        self.phase = "run"
        actions = [("banner", self.cfg["title"])]
        return actions + (self._talk("intro", self.cfg.get("intro")) or [])

    def spawn_rules(self):
        """(delay multiplier, max zombies alive, kind weights) or None when nothing should spawn."""
        if self.phase == "run":
            c = self.cfg
            return c["spawn_mul"], c["max_alive"], c["weights"]
        if self.phase == "event":
            ev = self.cfg["event"]
            return ev["spawn_mul"], ev["max_alive"], ev["weights"]
        if self.phase == "free":
            return DEFAULT_SPAWN
        return None

    def bounds(self):
        """(left, right) walls the player cannot cross, right may be None. None = no walls."""
        if self.phase == "free":
            return None
        c = self.cfg
        if self.phase in ("arrive", "event", "outro"):
            return c["goal_x"] - 20.0, c["goal_x"] + 20.0  # the arena around the goal
        return c["start_x"] - 25.0, None

    def objective(self, player_x, kills):
        """(title, text) for the objective box."""
        if self.phase == "free":
            return tr("obj.free_title"), tr("obj.free_text")
        c = self.cfg
        title = tr(c["title"])
        if self.phase == "event":
            ev = c["event"]
            if ev["kind"] == "boss":
                return title, tr(ev["goal"])
            left = max(0, ev["need"] - (kills - self.event_base))
            return title, tr("obj.left", text=tr(ev["text"]), n=left)
        return title, tr("obj.dist", goal=tr(c["goal"]), d=max(0, int(c["goal_x"] - player_x)))


class Dialogue:
    """A blocking conversation with a typewriter effect."""

    CHARS_PER_S = 55.0

    def __init__(self):
        self.lines = ()
        self.index = 0
        self.t = 0.0

    def start(self, lines):
        self.lines, self.index, self.t = tuple(lines), 0, 0.0

    @property
    def speaker(self):
        return self.lines[self.index][0]

    @property
    def text(self):
        return tr(self.lines[self.index][1])

    def visible_chars(self):
        return int(self.t * self.CHARS_PER_S)

    def press(self):
        """Space / click: finish typing the line, or go to the next one. True when the dialogue is over."""
        if self.visible_chars() < len(self.text):
            self.t = 1e6
            return False
        self.index += 1
        self.t = 0.0
        return self.index >= len(self.lines)


def wrap_text(font, text, max_width):
    """Split `text` into lines that fit into `max_width` pixels."""
    lines, current = [], ""
    for word in text.split(" "):
        trial = (current + " " + word).strip()
        if current and font.size(trial)[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def draw_portrait(surface, who, cx, cy):
    if who == "me":
        pygame.draw.circle(surface, COLOR_TEXT, (cx, cy - 8), 20, 4)
        pygame.draw.circle(surface, COLOR_ACCENT, (cx + 8, cy - 11), 3)
        pygame.draw.line(surface, COLOR_TEXT, (cx, cy + 12), (cx, cy + 36), 5)
    elif who == "vera":
        pygame.draw.circle(surface, (244, 200, 170), (cx, cy - 4), 22)
        pygame.draw.arc(surface, COLOR_ACCENT, (cx - 26, cy - 30, 52, 48), 0.0, math.pi,
                        4)  # headset band
        pygame.draw.rect(surface, COLOR_ACCENT, (cx - 30, cy - 8, 8, 16), border_radius=3)
        pygame.draw.line(surface, COLOR_ACCENT, (cx - 26, cy + 6), (cx - 8, cy + 18), 3)
        pygame.draw.circle(surface, (30, 40, 60), (cx - 7, cy - 6), 3)
        pygame.draw.circle(surface, (30, 40, 60), (cx + 8, cy - 6), 3)
    elif who == "warden":
        pygame.draw.circle(surface, (150, 96, 90), (cx, cy - 2), 24)
        pygame.draw.circle(surface, COLOR_ZOMBIE_EYE, (cx - 9, cy - 8), 5)
        pygame.draw.circle(surface, COLOR_ZOMBIE_EYE, (cx + 9, cy - 8), 5)
        pygame.draw.lines(surface, (40, 10, 14), False,
                          [(cx - 12, cy + 10), (cx - 6, cy + 16), (cx, cy + 10), (cx + 6, cy + 16),
                           (cx + 12, cy + 10)], 3)
    elif who == "butcher":
        pygame.draw.circle(surface, (128, 150, 100), (cx, cy - 2), 24)
        pygame.draw.rect(surface, COLOR_TEXT, (cx - 22, cy - 28, 44, 10),
                         border_radius=4)  # white cap
        pygame.draw.circle(surface, COLOR_ZOMBIE_EYE, (cx - 9, cy - 8), 5)
        pygame.draw.circle(surface, COLOR_ZOMBIE_EYE, (cx + 9, cy - 8), 5)
        pygame.draw.rect(surface, (40, 10, 14), (cx - 10, cy + 8, 20, 8), border_radius=2)
        pygame.draw.rect(surface, COLOR_TEXT, (cx - 6, cy + 8, 4, 4))
        pygame.draw.rect(surface, COLOR_TEXT, (cx + 2, cy + 8, 4, 4))
    else:  # narrator: a crescent moon
        pygame.draw.circle(surface, COLOR_METAL, (cx, cy), 24)
        pygame.draw.circle(surface, COLOR_BUTTON, (cx + 12, cy - 6), 21)


def draw_dialogue(surface, fonts, dialogue):
    box = pygame.Rect(60, 440, WINDOW_WIDTH - 120, 180)
    pygame.draw.rect(surface, COLOR_PANEL, box, border_radius=14)
    pygame.draw.rect(surface, COLOR_PANEL_EDGE, box, width=2, border_radius=14)
    name_key, color = SPEAKERS[dialogue.speaker]
    name = tr(name_key)
    cx, cy = box.left + 76, box.top + 90
    pygame.draw.circle(surface, COLOR_BUTTON, (cx, cy), 50)
    pygame.draw.circle(surface, color, (cx, cy), 50, 3)
    draw_portrait(surface, dialogue.speaker, cx, cy)
    text_x = box.left + 150
    surface.blit(fonts["row"].render(name, True, color), (text_x, box.top + 14))
    remaining = dialogue.visible_chars()
    y = box.top + 48
    for line in wrap_text(fonts["dlg"], dialogue.text, box.right - text_x - 24):
        if remaining <= 0:
            break
        surface.blit(fonts["dlg"].render(line[:remaining], True, COLOR_TEXT), (text_x, y))
        remaining -= len(line) + 1
        y += 28
    if dialogue.visible_chars() >= len(dialogue.text):
        hint = fonts["desc"].render(tr("talk.hint"), True, COLOR_LABEL)
        surface.blit(hint, (box.right - hint.get_width() - 20, box.bottom - 28))


def draw_toast(surface, fonts, toast):
    """A radio message / hint at the bottom of the screen; the game keeps running."""
    who, spec, left = toast
    name_key, color = SPEAKERS[who]
    name = tr(name_key)
    text = tr_spec(spec)
    alpha = int(255 * clamp(left / 0.6, 0.0, 1.0))
    box = pygame.Rect(WINDOW_WIDTH // 2 - 390, 544, 780, 78)
    bg = pygame.Surface(box.size, pygame.SRCALPHA)
    pygame.draw.rect(bg, (15, 23, 42, 225), bg.get_rect(), border_radius=12)
    pygame.draw.rect(bg, (color[0], color[1], color[2], 255), bg.get_rect(), width=2,
                     border_radius=12)
    bg.set_alpha(alpha)
    surface.blit(bg, box.topleft)
    label = fonts["toast_b"].render(name + ":", True, color)
    label.set_alpha(alpha)
    surface.blit(label, (box.left + 16, box.top + 8))
    for i, line in enumerate(wrap_text(fonts["toast"], text, box.width - 32)[:2]):
        img = fonts["toast"].render(line, True, COLOR_TEXT)
        img.set_alpha(alpha)
        surface.blit(img, (box.left + 16, box.top + 32 + i * 22))


def draw_banner(surface, fonts, banner):
    """Big title in the middle of the screen (chapter name / fight name) that fades in and out."""
    key, left = banner
    text = tr(key)
    alpha = int(255 * clamp(min(left / 0.7, (BANNER_S - left) / 0.5), 0.0, 1.0))
    img = fonts["banner"].render(text, True, COLOR_TEXT)
    shadow = fonts["banner"].render(text, True, (0, 0, 0))
    img.set_alpha(alpha)
    shadow.set_alpha(alpha)
    x = WINDOW_WIDTH // 2 - img.get_width() // 2
    surface.blit(shadow, (x + 3, 183))
    surface.blit(img, (x, 180))


def draw_objective(surface, texts, fonts, story, player_x, kills):
    title, text = story.objective(player_x, kills)
    box = pygame.Rect(WINDOW_WIDTH - 20 - 400, 96, 400, 58)
    pygame.draw.rect(surface, COLOR_PANEL, box, border_radius=10)
    pygame.draw.rect(surface, COLOR_PANEL_EDGE, box, width=2, border_radius=10)
    surface.blit(texts.get(fonts["desc"], title, COLOR_ACCENT), (box.left + 14, box.top + 8))
    surface.blit(texts.get(fonts["toast_b"], text, COLOR_TEXT), (box.left + 14, box.top + 28))


def draw_boss_bar(surface, texts, fonts, boss, name):
    ratio = clamp(boss.hp / boss.max_hp, 0.0, 1.0)
    bar = pygame.Rect(WINDOW_WIDTH // 2 - 230, 514, 460, 16)
    label = texts.get(fonts["toast_b"], name, COLOR_BAD)
    surface.blit(label, (bar.centerx - label.get_width() // 2, bar.top - 24))
    pygame.draw.rect(surface, COLOR_PANEL, bar, border_radius=6)
    if ratio > 0.0:
        pygame.draw.rect(surface, COLOR_BAD,
                         (bar.left, bar.top, int(bar.width * ratio), bar.height), border_radius=6)
    pygame.draw.rect(surface, COLOR_PANEL_EDGE, bar, width=2, border_radius=6)


def draw_barrier(surface, camera_x, x_m, t):
    """A dashed red line: the edge of the arena during a fight."""
    sx = int(x_m * PIXELS_PER_METER - camera_x)
    if sx < -10 or sx > WINDOW_WIDTH + 10:
        return
    phase = int(t * 4.0)
    for y in range(0, int(GROUND_LEVEL_M * PIXELS_PER_METER), 28):
        if (y // 28 + phase) % 2 == 0:
            pygame.draw.line(surface, COLOR_BAD, (sx, y), (sx, y + 14), 2)


FAR_TOWER_PARALLAX = 0.012  # how slowly the distant radio tower slides across the horizon


def draw_far_tower(surface, camera_x, progress, t, lit):
    """The radio tower on the horizon: it is your goal and it gets bigger as you come closer."""
    base_y = GROUND_LEVEL_M * PIXELS_PER_METER - 70
    sx = 1090 - FAR_TOWER_PARALLAX * (camera_x + 440)
    h = lerp(70, 170, clamp(progress, 0.0, 1.0))
    w = h * 0.16
    color = (30, 44, 92)
    pygame.draw.line(surface, color, (sx - w, base_y), (sx - 2, base_y - h), 2)
    pygame.draw.line(surface, color, (sx + w, base_y), (sx + 2, base_y - h), 2)
    for i in range(1, 6):
        y = base_y - h * i / 6
        half = lerp(w, 2, i / 6)
        pygame.draw.line(surface, color, (sx - half, y), (sx + half, y), 1)
    if lit:
        light = COLOR_GOOD
    else:
        light = COLOR_BAD if int(t * 2.0) % 2 == 0 else (90, 20, 20)
    pygame.draw.circle(surface, light, (int(sx), int(base_y - h - 3)), 3)


def draw_landmark(surface, camera_x, kind, x_m, ground_level_m, t, lit=False):
    """Simple silhouettes of the places the story visits (they stand in the world, drawn in front of the ground)."""
    gx = x_m * PIXELS_PER_METER - camera_x
    if gx < -420 or gx > WINDOW_WIDTH + 420:
        return
    base = ground_level_m * PIXELS_PER_METER
    dark = (12, 18, 40)
    edge = (44, 60, 110)
    window = (250, 204, 21)
    if kind == "station":
        pygame.draw.rect(surface, dark, (gx - 120, base - 150, 240, 16))
        pygame.draw.rect(surface, edge, (gx - 120, base - 150, 240, 3))
        for px in (-104, 96):
            pygame.draw.rect(surface, dark, (gx + px, base - 134, 10, 134))
        for px in (-50, 22):
            pygame.draw.rect(surface, dark, (gx + px, base - 62, 26, 62), border_radius=3)
            pygame.draw.rect(surface, COLOR_GOOD, (gx + px + 5, base - 52, 16, 12))
        pygame.draw.rect(surface, dark, (gx + 140, base - 105, 130, 105))
        pygame.draw.rect(surface, edge, (gx + 140, base - 105, 130, 105), width=2)
        pygame.draw.rect(surface, window, (gx + 160, base - 80, 40, 30))
        pygame.draw.rect(surface, (160, 30, 30), (gx - 100, base - 172, 60, 20))
    elif kind == "camp":
        for dx, h in ((-250, 80), (-130, 96)):
            tent = [(gx + dx - 60, base), (gx + dx, base - h), (gx + dx + 60, base)]
            pygame.draw.polygon(surface, (20, 44, 64), tent)
            pygame.draw.polygon(surface, edge, tent, 2)
        for i in range(5):
            x0 = gx + 20 + i * 26
            pygame.draw.line(surface, (70, 48, 30), (x0, base), (x0 + 40, base - 70), 6)
            pygame.draw.line(surface, (70, 48, 30), (x0 + 40, base), (x0, base - 70), 6)
        pygame.draw.line(surface, (90, 62, 38), (gx + 10, base - 36), (gx + 170, base - 36), 6)
        pygame.draw.rect(surface, dark, (gx + 210, base - 44, 28, 44))
        flick = 10 + 6 * math.sin(t * 13.0) + 3 * math.sin(t * 7.3)
        pygame.draw.polygon(surface, COLOR_FIRE,
                            [(gx + 214, base - 44), (gx + 224, base - 66 - flick),
                             (gx + 234, base - 44)])
        pygame.draw.polygon(surface, COLOR_FIRE_CORE,
                            [(gx + 218, base - 44), (gx + 224, base - 56 - flick * 0.5),
                             (gx + 230, base - 44)])
    elif kind == "bridge":
        for px in (-170, 130):
            pygame.draw.rect(surface, dark, (gx + px, base - 230, 40, 230))
            pygame.draw.rect(surface, edge, (gx + px, base - 230, 40, 230), width=2)
        pygame.draw.polygon(surface, dark,
                            [(gx - 420, base - 230), (gx - 30, base - 230), (gx + 20, base - 190),
                             (gx - 30, base - 212), (gx - 420, base - 212)])
        pygame.draw.polygon(surface, dark,
                            [(gx + 420, base - 230), (gx + 60, base - 230), (gx + 30, base - 170),
                             (gx + 90, base - 212), (gx + 420, base - 212)])
        for px in (-150, 150):
            pygame.draw.line(surface, edge, (gx + px, base - 230),
                             (gx + px + (-60 if px < 0 else 60), base - 214), 1)
    elif kind == "tower":
        top = base - 430
        for side in (-1, 1):
            pygame.draw.line(surface, edge, (gx + side * 70, base), (gx + side * 6, top), 5)
        for i in range(8):
            ya, yb = base - i * 54, base - (i + 1) * 54
            wa = 70 - 64 * (i * 54) / 430
            wb = 70 - 64 * ((i + 1) * 54) / 430
            pygame.draw.line(surface, edge, (gx - wa, ya), (gx + wb, yb), 2)
            pygame.draw.line(surface, edge, (gx + wa, ya), (gx - wb, yb), 2)
            pygame.draw.line(surface, edge, (gx - wb, yb), (gx + wb, yb), 2)
        pygame.draw.line(surface, edge, (gx, top), (gx, top - 50), 3)
        if lit:
            light = COLOR_GOOD
            for radius in (14, 24, 36):
                pygame.draw.circle(surface, light, (int(gx), int(top - 52)), radius, 1)
        else:
            light = COLOR_BAD if int(t * 2.0) % 2 == 0 else (90, 20, 20)
        pygame.draw.circle(surface, light, (int(gx), int(top - 52)), 6)
        pygame.draw.rect(surface, dark, (gx + 90, base - 80, 130, 80))
        pygame.draw.rect(surface, edge, (gx + 90, base - 80, 130, 80), width=2)
        pygame.draw.rect(surface, COLOR_GOOD if lit else window, (gx + 112, base - 58, 36, 28))
    elif kind == "hospital":
        pygame.draw.rect(surface, dark, (gx + 150, base - 140, 120, 140))  # side wing
        pygame.draw.rect(surface, edge, (gx + 150, base - 140, 120, 140), width=2)
        pygame.draw.rect(surface, window, (gx + 182, base - 100, 24, 24))
        pygame.draw.rect(surface, dark, (gx - 150, base - 230, 300, 230))  # main block
        pygame.draw.rect(surface, edge, (gx - 150, base - 230, 300, 230), width=2)
        for row in range(3):
            for col in range(6):
                wx, wy = gx - 132 + col * 48, base - 208 + row * 54
                glow = (row * 7 + col * 3) % 5 == 0 and not (
                        row == 1 and col == 3 and int(t * 5.0) % 3 == 0)
                pygame.draw.rect(surface, window if glow else (22, 30, 60), (wx, wy, 28, 28))
        pygame.draw.rect(surface, COLOR_BAD, (gx - 6, base - 266, 12, 36))  # red cross on the roof
        pygame.draw.rect(surface, COLOR_BAD, (gx - 18, base - 254, 36, 12))
        pygame.draw.rect(surface, (22, 30, 60), (gx - 20, base - 46, 40, 46))  # entrance
        pygame.draw.rect(surface, COLOR_GOOD, (gx - 8, base - 58, 16, 6))
    elif kind == "tunnel":
        hill = [(gx - 330, base), (gx - 250, base - 200), (gx + 250, base - 200), (gx + 330, base)]
        pygame.draw.polygon(surface, dark, hill)
        pygame.draw.polygon(surface, edge, hill, 2)
        pygame.draw.rect(surface, (2, 4, 12), (gx - 95, base - 120, 190, 120))  # the black arch
        pygame.draw.ellipse(surface, (2, 4, 12), (gx - 95, base - 168, 190, 96))
        pygame.draw.arc(surface, edge, (gx - 99, base - 172, 198, 104), 0.0, math.pi, 4)
        pygame.draw.line(surface, edge, (gx - 99, base - 120), (gx - 99, base), 4)
        pygame.draw.line(surface, edge, (gx + 99, base - 120), (gx + 99, base), 4)
        pygame.draw.circle(surface, COLOR_BAD if int(t * 2.5) % 2 == 0 else (90, 20, 20),
                           (int(gx), int(base - 188)), 6)  # warning lamp
        for i in range(-8, 9):  # rail sleepers
            pygame.draw.rect(surface, (52, 38, 28), (gx + i * 30 - 6, base + 2, 12, 5))
        pygame.draw.line(surface, COLOR_METAL_DARK, (gx - 300, base + 3), (gx + 300, base + 3), 2)


# =============================================================================
# 8. MAIN LOOP & CAMERA
# =============================================================================

def aim_angle(player, mouse_pos, camera_x):
    """Angle from the player's hand to the mouse cursor (world space)."""
    hand = player.hand_position()
    tx = (mouse_pos[0] + camera_x) / PIXELS_PER_METER
    ty = mouse_pos[1] / PIXELS_PER_METER
    return math.atan2(ty - hand.y, tx - hand.x)


def main():
    os.environ.setdefault("SDL_RENDER_SCALE_QUALITY",
                          "linear")  # smooth scaling in full-screen mode
    pygame.init()
    pygame.display.set_caption(tr("window_title"))
    fullscreen = START_FULLSCREEN or ("--fullscreen" in sys.argv)
    screen = make_screen(fullscreen)
    clock = pygame.time.Clock()

    hud_font = pygame.font.SysFont("Consolas", 14)
    measure_font = pygame.font.SysFont("Consolas", 12, bold=True)
    title_font = pygame.font.SysFont("Arial", 15, bold=True)
    score_font = pygame.font.SysFont("Arial", 26, bold=True)
    big_font = pygame.font.SysFont("Arial", 72, bold=True)
    small_font = pygame.font.SysFont("Arial", 12, bold=True)
    ui_fonts = {
        "title": pygame.font.SysFont("Arial", 36, bold=True),
        "huge": pygame.font.SysFont("Arial", 64, bold=True),
        "banner": pygame.font.SysFont("Arial", 46, bold=True),
        "btn": pygame.font.SysFont("Arial", 22, bold=True),
        "row": pygame.font.SysFont("Arial", 19, bold=True),
        "dlg": pygame.font.SysFont("Arial", 21),
        "toast": pygame.font.SysFont("Arial", 17),
        "toast_b": pygame.font.SysFont("Arial", 17, bold=True),
        "desc": pygame.font.SysFont("Arial", 14),
    }

    texts = TextCache()
    scenery = Scenery(GROUND_LEVEL_M)
    particles = ParticleSystem()
    fx_layer = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA).convert_alpha()
    telemetry = TelemetryPanel(hud_font)
    hurt_vignette = build_hurt_vignette()
    dim_overlay = build_dim_overlay()
    blast_radius_px = int(ROCKET_BLAST_RADIUS_M * PIXELS_PER_METER)
    blast_glow = make_glow(int(blast_radius_px * 1.3), (255, 150, 60), 0.9)

    collected = set()
    knives = []
    shots = []  # bullets and rockets
    blasts = []  # [x_m, y_m, age_s] of explosions (for the shock ring)
    zombies = []
    kills = 0
    spawn_timer = 3.0

    player = Stickman(x_m=2.0, y_m=4.0)
    camera_x = player.position.x * PIXELS_PER_METER - WINDOW_WIDTH / 2

    story = None  # Story object in the story mode, None in the endless "free run"
    dialogue = Dialogue()
    toast = None  # [who, text, seconds_left] - a radio message at the bottom
    banner = None  # [text, seconds_left] - a big title in the middle
    boss = None  # the Zombie that is the current boss
    play_time = 0.0  # seconds spent in the story [s]

    state = "title"  # title | play | pause | shop | talk | win  (everything freezes outside "play")
    shop_from = "play"  # where the shop returns to when it is closed
    shop_msg, shop_msg_ok, shop_msg_t = "", True, 0.0
    mouse_lock = False  # a menu click must not also fire a shot while the button is still held

    show_hud = False
    show_grid = True
    pickup_flash = 0.0
    kill_flash = 0.0
    hurt_flash = 0.0
    t = 0.0  # animation clock [s]

    def settle(p):
        """Let the stickman fall to the ground before the scene is shown."""
        for _ in range(90):
            p.update(1 / 60, 0.0, GROUND_LEVEL_M, False)

    settle(player)

    def explode_at(x_m, y_m, damage):
        """A rocket went off: visuals + area damage."""
        nonlocal kills, kill_flash
        particles.explosion(x_m, y_m)
        blasts.append([x_m, y_m, 0.0])
        died = blast_zombies(x_m, y_m, damage, ROCKET_BLAST_RADIUS_M, zombies, GROUND_LEVEL_M,
                             particles)
        if died:
            kills += died
            kill_flash = 0.4

    def handle(actions):
        """Carry out what the story asked for: dialogues, radio messages, rewards, the boss..."""
        nonlocal state, toast, banner, boss, pickup_flash
        for act in actions:
            kind = act[0]
            if kind == "talk":
                dialogue.start(act[1])
                state = "talk"
            elif kind == "toast":
                toast = [act[1], act[2], TOAST_S]
            elif kind == "banner":
                banner = [act[1], BANNER_S]
            elif kind == "reward":
                player.bonus += act[1]
                toast = ["loot", ("toast.loot", {"n": act[1], "what_key": act[2]}), TOAST_S]
                pickup_flash = 0.6
                for _ in range(3):
                    particles.sparkle(player.position.x, player.position.y - 0.4)
            elif kind == "spawn_boss":
                boss = Zombie(player.position.x + 11.0, act[1])
                zombies.append(boss)
            elif kind == "victory":
                state = "win"

    def advance_dialogue(skip):
        nonlocal state
        if skip or dialogue.press():
            state = "play"
            handle(story.after_talk() if story is not None else [])

    def reset_world():
        nonlocal camera_x, spawn_timer, hurt_flash, boss, toast, banner
        knives.clear()
        shots.clear()
        blasts.clear()
        zombies.clear()
        particles.items.clear()
        camera_x = player.position.x * PIXELS_PER_METER - WINDOW_WIDTH / 2
        spawn_timer = 3.0
        hurt_flash = 0.0
        boss = None
        toast = None
        banner = None

    def begin_game(mode, chapter=0):
        """A fresh game: mode = "story" or "free". `chapter` = where the story starts (chapter select)."""
        nonlocal story, player, kills, play_time, pickup_flash, kill_flash, state
        story = Story(chapter) if mode == "story" else None
        player = Stickman(x_m=CHAPTERS[chapter]["start_x"] if story is not None else 2.0, y_m=4.0)
        settle(player)
        if story is not None:
            # starting in a later chapter: you get the loot of the chapters you skipped
            player.bonus += sum(c["reward"] for c in CHAPTERS[:chapter])
        collected.clear()
        kills = 0
        play_time = 0.0
        pickup_flash = kill_flash = 0.0
        reset_world()
        state = "play"
        if story is not None:
            handle(story.begin())

    def retry_chapter():
        """Story: back to the checkpoint (start of the chapter). Weapons, upgrades and orbs are kept."""
        nonlocal state
        player.respawn(story.cfg["start_x"])
        settle(player)
        player.invuln = 1.5
        reset_world()
        state = "play"
        handle(story.retry())

    def go_title():
        nonlocal state
        begin_game("free")
        state = "title"

    def apply_language(code):
        set_language(code)
        pygame.display.set_caption(tr("window_title"))

    running = True
    while running:
        dt_ms = clock.tick(FPS)
        dt = min(dt_ms / 1000.0, 0.05)  # a lag spike must not teleport knives and zombies
        dead = player.hp <= 0
        story_on = story is not None and story.phase != "free"
        restart = False
        mouse = pygame.mouse.get_pos()
        shop_msg_t = max(0.0, shop_msg_t - dt)

        # ---------------------------------------------------------------- events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                key = event.key
                if key == pygame.K_F11 or (
                        key == pygame.K_RETURN and getattr(event, "mod", 0) & pygame.KMOD_ALT):
                    fullscreen = not fullscreen
                    screen = make_screen(fullscreen)
                elif key == pygame.K_l and state in ("title", "pause", "chapters", "win"):
                    apply_language(next_language())
                elif state == "talk":
                    if key in (pygame.K_SPACE, pygame.K_RETURN):
                        advance_dialogue(False)
                    elif key == pygame.K_ESCAPE:
                        advance_dialogue(True)  # skip the whole conversation
                elif state == "chapters":
                    if key == pygame.K_ESCAPE:
                        state = "title"
                elif state in ("title", "win"):
                    pass
                elif key in (pygame.K_ESCAPE, pygame.K_p):
                    if state == "play":
                        state = "pause"
                    elif state == "pause":
                        state = "play"
                    else:
                        state = shop_from  # close the shop
                elif key == pygame.K_b:
                    if state == "shop":
                        state = shop_from
                    elif not dead:
                        shop_from = state
                        state = "shop"
                elif key == pygame.K_h:
                    show_hud = not show_hud
                elif key == pygame.K_g:
                    show_grid = not show_grid
                elif key == pygame.K_r and state in ("play", "pause"):
                    restart = True
                elif state == "play" and not dead:
                    if key in JUMP_KEYS:
                        player.press_jump()
                    elif key in THROW_KEYS:
                        player.request_throw()
                    elif pygame.K_1 <= key <= pygame.K_4:
                        player.equip(WEAPON_ORDER[key - pygame.K_1])
            elif event.type == pygame.MOUSEWHEEL:
                if state == "play" and not dead:
                    owned = [k for k in WEAPON_ORDER if k in player.weapons_owned]
                    if len(owned) > 1:
                        player.equip(owned[(owned.index(player.weapon) - event.y) % len(owned)])
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_lock = True
                if state == "title":
                    lang = pick_language(event.pos, TITLE_LANG_RECTS)
                    action = None if lang else pick_button(event.pos, TITLE_KEYS, TITLE_RECTS)
                    if lang:
                        apply_language(lang)
                    elif action == "story":
                        begin_game("story")
                    elif action == "chapters":
                        state = "chapters"
                    elif action == "free":
                        begin_game("free")
                    elif action == "fullscreen":
                        fullscreen = not fullscreen
                        screen = make_screen(fullscreen)
                    elif action == "quit":
                        running = False
                elif state == "chapters":
                    action = pick_button(event.pos, CHAPTER_KEYS, CHAPTER_RECTS)
                    if action == "back":
                        state = "title"
                    elif isinstance(action, int) and action <= unlocked_chapters():
                        begin_game("story", action)
                elif state == "win":
                    action = pick_button(event.pos, WIN_KEYS, WIN_RECTS)
                    if action == "continue":
                        state = "play"
                    elif action == "title":
                        go_title()
                elif state == "talk":
                    advance_dialogue(False)
                elif state == "play":
                    if SHOP_BUTTON.collidepoint(event.pos):
                        if not dead:
                            shop_from = "play"
                            state = "shop"
                    elif PAUSE_BUTTON.collidepoint(event.pos):
                        state = "pause"
                    elif not dead:
                        mouse_lock = False  # a real shot: holding the button keeps shooting
                        player.request_throw(aim_angle(player, event.pos, camera_x))
                elif state == "pause":
                    lang = pick_language(event.pos, PAUSE_LANG_RECTS)
                    action = None if lang else pick_button(event.pos, PAUSE_KEYS, PAUSE_RECTS)
                    if lang:
                        apply_language(lang)
                    elif action == "resume":
                        state = "play"
                    elif action == "shop" and not dead:
                        shop_from = "pause"
                        state = "shop"
                    elif action == "restart":
                        restart = True
                    elif action == "fullscreen":
                        fullscreen = not fullscreen
                        screen = make_screen(fullscreen)
                    elif action == "title":
                        go_title()
                    elif action == "quit":
                        running = False
                elif state == "shop":
                    if SHOP_CLOSE.collidepoint(event.pos):
                        state = shop_from
                    else:
                        result = shop_click(event.pos, player,
                                            shop_balance(player, len(collected), kills))
                        if result:
                            shop_msg, shop_msg_ok = result
                            shop_msg_t = 2.5

        if not pygame.mouse.get_pressed()[0]:
            mouse_lock = False

        if restart:
            if story_on:
                retry_chapter()
            else:
                begin_game("free" if story is None or story.phase == "free" else "story")

        # Reaching a chapter unlocks it in the chapter select (saved to the settings file)
        if story is not None and story.chapter > SETTINGS["unlocked"]:
            SETTINGS["unlocked"] = story.chapter
            save_settings()

        # ---------------------------------------------------------------- simulation
        if state in ("title", "chapters"):
            t += dt  # only the scenery animates behind the title
        elif state == "play":
            t += dt
            if story is not None:
                play_time += dt
            if toast is not None:
                toast[2] -= dt
                if toast[2] <= 0.0:
                    toast = None
            if banner is not None:
                banner[1] -= dt
                if banner[1] <= 0.0:
                    banner = None

            # Continuous input (arrows, A/D for QWERTY, Q/D for AZERTY)
            keys = pygame.key.get_pressed()
            move_input = 0.0
            if not dead:
                if keys[pygame.K_LEFT] or keys[pygame.K_a] or keys[pygame.K_q]:
                    move_input -= 1.0
                if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                    move_input += 1.0
                # Holding the throw key / left mouse button keeps shooting (limited by the cooldown)
                if any(keys[k] for k in THROW_KEYS):
                    player.request_throw()
                if pygame.mouse.get_pressed()[0] and not mouse_lock:
                    player.request_throw(aim_angle(player, pygame.mouse.get_pos(), camera_x))
            jump_held = (not dead) and any(keys[k] for k in JUMP_KEYS)

            player.update(dt, move_input, GROUND_LEVEL_M, jump_held)

            # Invisible walls: the arena during a fight, and "no way back" to the previous chapter
            if story is not None:
                walls = story.bounds()
                if walls is not None:
                    lo, hi = walls
                    if player.position.x < lo:
                        player.position.x = lo
                        player.velocity.x = max(0.0, player.velocity.x)
                    if hi is not None and player.position.x > hi:
                        player.position.x = hi
                        player.velocity.x = min(0.0, player.velocity.x)

            # Turn physics events into visual feedback
            feet_x, feet_y = player.position.x, GROUND_LEVEL_M
            for kind, value in player.events:
                if kind == "land":
                    particles.dust(feet_x, feet_y, int(5 + value * 3), spread=1.0 + value * 0.4)
                elif kind == "jump":
                    particles.dust(feet_x, feet_y, 5, spread=1.2)
                elif kind == "step":
                    particles.dust(feet_x, feet_y, 2, spread=0.5, bias_vx=-value * 0.12)
                elif kind == "skid":
                    particles.dust(feet_x, feet_y, 3, spread=0.7, bias_vx=value * 0.15)
                elif kind == "throw":
                    # `value` is the aim angle of the equipped weapon
                    cfg = WEAPONS[player.weapon]
                    damage = player.weapon_damage()
                    hand = player.hand_position()
                    if player.weapon == "knife":
                        # the knife inherits a bit of the runner's speed
                        if len(knives) >= MAX_KNIVES:
                            knives.pop(0)
                        knives.append(Knife(
                            hand.x, hand.y,
                            math.cos(value) * KNIFE_SPEED + player.velocity.x * 0.35,
                            math.sin(value) * KNIFE_SPEED + player.velocity.y * 0.35,
                            damage,
                        ))
                    else:
                        angle = value + random.uniform(-cfg["spread"], cfg["spread"])
                        dx, dy = math.cos(angle), math.sin(angle)
                        mx, my = hand.x + dx * 0.5, hand.y + dy * 0.5  # muzzle
                        if len(shots) >= MAX_SHOTS:
                            shots.pop(0)
                        shots.append(Projectile(
                            "rocket" if player.weapon == "rocket" else "bullet",
                            mx, my, dx * cfg["speed"], dy * cfg["speed"], damage,
                        ))
                        if player.weapon == "rocket":
                            for _ in range(3):
                                particles.smoke(mx, my)
                        else:
                            particles.muzzle(mx, my, angle)

            for ox, oy in collect_orbs(player, collected, GROUND_LEVEL_M):
                particles.sparkle(ox, oy)
                pickup_flash = 0.4

            # --- Knives and bullets / rockets in flight ------------------------
            for k in knives:
                if k.update(dt, GROUND_LEVEL_M):
                    particles.dust(k.x, GROUND_LEVEL_M, 3, spread=0.4)
            for s in shots:
                if s.update(dt, GROUND_LEVEL_M):  # hit the floor
                    if s.kind == "rocket":
                        explode_at(s.x, GROUND_LEVEL_M, s.damage)
                    else:
                        particles.dust(s.x, GROUND_LEVEL_M, 2, spread=0.3)
                elif s.kind == "rocket":
                    particles.smoke(s.x - math.cos(s.angle) * 0.25, s.y - math.sin(s.angle) * 0.25)

            # --- Zombies: random spawning off-screen, walking, biting ----------
            if not dead:
                rules = DEFAULT_SPAWN if story is None else story.spawn_rules()
                spawn_timer -= dt
                if spawn_timer <= 0.0:
                    if rules is None:
                        spawn_timer = 1.0
                    else:
                        delay_mul, max_alive, weights = rules
                        # In the endless mode the more zombies you kill, the faster they keep coming (down to 45 %)
                        speedup = max(0.45,
                                      1.0 - kills * 0.015) if story is None or story.phase == "free" else 1.0
                        spawn_timer = random.uniform(ZOMBIE_SPAWN_MIN_S,
                                                     ZOMBIE_SPAWN_MAX_S) * delay_mul * speedup
                        can_spawn = len(zombies) < max_alive
                        if can_spawn and story is not None and story.phase == "event" \
                                and story.cfg["event"]["kind"] == "kills":
                            # do not spawn more zombies than are still needed for the objective
                            walking = sum(1 for z in zombies if z.state == "walk")
                            can_spawn = walking + (kills - story.event_base) < story.cfg["event"][
                                "need"]
                        if can_spawn:
                            side = random.choice((-1, 1))
                            zx = player.position.x + side * random.uniform(*ZOMBIE_SPAWN_DIST_M)
                            zombies.append(Zombie(zx, pick_zombie_kind(weights)))

            for z in zombies:
                z.update(dt, player.position.x)
                if not dead and ZOMBIES_HURT_PLAYER and z.touches(player, GROUND_LEVEL_M):
                    to_zombie = 1 if z.x > player.position.x else -1
                    if player.hurt(to_zombie, z.cfg.get("bite", 1)):
                        z.attack_cd = ZOMBIE_ATTACK_PAUSE_S
                        hurt_flash = 0.35
                        particles.gore(player.position.x, player.position.y, 8, -to_zombie)

            # --- Knife vs zombie -----------------------------------------------
            for k in knives:
                if k.stuck or k.dead:
                    continue
                for z in zombies:
                    if z.state != "walk":
                        continue
                    if z.hit_by(k.prev_x, k.prev_y, k.x, k.y, GROUND_LEVEL_M):
                        push = 1 if k.vx > 0.0 else -1
                        killed = z.hit(push, k.damage)
                        particles.gore(k.x, k.y, 18 if killed else 7, push)
                        k.dead = True
                        if killed:
                            kills += 1
                            kill_flash = 0.4
                        break

            # --- Bullet / rocket vs zombie -------------------------------------
            for s in shots:
                if s.dead:
                    continue
                for z in zombies:
                    if z.state != "walk":
                        continue
                    if z.hit_by(s.prev_x, s.prev_y, s.x, s.y, GROUND_LEVEL_M):
                        s.dead = True
                        if s.kind == "rocket":
                            explode_at(s.x, s.y, s.damage)
                        else:
                            push = 1 if s.vx > 0.0 else -1
                            killed = z.hit(push, s.damage)
                            particles.gore(s.x, s.y, 14 if killed else 5, push)
                            if killed:
                                kills += 1
                                kill_flash = 0.4
                        break

            knives = [k for k in knives
                      if not k.dead and not (k.stuck and k.stuck_time <= 0.0)
                      and abs(k.x - player.position.x) < 25.0]
            shots = [s for s in shots if not s.dead and abs(s.x - player.position.x) < 30.0]
            zombies = [z for z in zombies
                       if not z.remove and abs(z.x - player.position.x) < ZOMBIE_DESPAWN_DIST_M]

            for b in blasts:
                b[2] += dt
            blasts = [b for b in blasts if b[2] < 0.4]

            pickup_flash = max(0.0, pickup_flash - dt)
            kill_flash = max(0.0, kill_flash - dt)
            hurt_flash = max(0.0, hurt_flash - dt)
            particles.update(dt)

            # --- The story reacts to what happened ------------------------------
            if story is not None and not dead:
                boss_dead = boss is not None and boss.state == "dying" and boss.death_time > 1.0
                handle(story.update(player.position.x, kills, boss_dead))

            # Smooth camera follow (frame-rate independent) with a little look-ahead
            camera_target = (
                                    player.position.x + player.velocity.x * CAMERA_LOOKAHEAD_S) * PIXELS_PER_METER \
                            - WINDOW_WIDTH / 2
            camera_x += (camera_target - camera_x) * (1.0 - math.exp(-CAMERA_STIFFNESS * dt))
        elif state == "talk":
            dialogue.t += dt

        # ---------------------------------------------------------------- render (back to front)
        balance = shop_balance(player, len(collected), kills)

        scenery.draw_background(screen, camera_x, t)
        if story is not None:
            draw_far_tower(screen, camera_x, player.position.x / TOWER_X_M, t, story.beacon_lit)
        scenery.draw_ground(screen, camera_x, t, measure_font, player, show_grid)
        scenery.draw_orbs(screen, camera_x, GROUND_LEVEL_M, collected, t)
        if story is not None:
            for i, chapter in enumerate(CHAPTERS):
                lit = story.beacon_lit and i == len(CHAPTERS) - 1
                draw_landmark(screen, camera_x, chapter["landmark"], chapter["goal_x"],
                              GROUND_LEVEL_M, t, lit)
            if story.phase == "event":
                walls = story.bounds()
                draw_barrier(screen, camera_x, walls[0], t)
                draw_barrier(screen, camera_x, walls[1], t)
        player.draw_shadow(screen, camera_x, GROUND_LEVEL_M)
        visible = [z for z in zombies if
                   -150 < z.x * PIXELS_PER_METER - camera_x < WINDOW_WIDTH + 150]
        for z in visible:
            z.draw_shadow(screen, camera_x, GROUND_LEVEL_M)
        for z in visible:
            z.draw(screen, camera_x, GROUND_LEVEL_M)
        if player.invuln <= 0.0 or int(t * 16) % 2 == 0:  # blinks after a bite
            player.draw(screen, camera_x, GROUND_LEVEL_M,
                        debug=show_hud and state not in ("title", "chapters"))
        for k in knives:
            k.draw(screen, camera_x)
        for s in shots:
            s.draw(screen, camera_x)
        for bx, by, age in blasts:  # explosion flash + shock ring
            sx, sy = int(bx * PIXELS_PER_METER - camera_x), int(by * PIXELS_PER_METER)
            if age < 0.14:
                gr = blast_glow.get_width() // 2
                screen.blit(blast_glow, (sx - gr, sy - gr), special_flags=pygame.BLEND_RGB_ADD)
            k_ = age / 0.4
            ring = int(lerp(12, blast_radius_px, 1.0 - (1.0 - k_) ** 2))
            pygame.draw.circle(screen, lerp_color(COLOR_FIRE_CORE, (120, 40, 30), k_), (sx, sy),
                               ring,
                               width=max(1, int(6 * (1.0 - k_))))
        particles.draw(screen, fx_layer, camera_x)
        scenery.draw_fireflies(screen, camera_x, t)

        if state in ("title", "chapters"):
            if state == "title":
                draw_title(screen, texts, ui_fonts, mouse, dim_overlay, fullscreen)
            else:
                draw_chapters(screen, texts, ui_fonts, mouse, dim_overlay)
            pygame.display.flip()
            continue

        if hurt_flash > 0.0:
            hurt_vignette.set_alpha(int(255 * min(1.0, hurt_flash / 0.35)))
            screen.blit(hurt_vignette, (0, 0))

        if show_hud:
            telemetry.draw(screen, dt, player, dt_ms, GROUND_LEVEL_M, len(collected), kills,
                           len(zombies))
            legend = texts.get(hud_font, tr("hud.legend"), COLOR_VELOCITY)
            screen.blit(legend, (WINDOW_WIDTH - legend.get_width() - 20, 66))
        draw_counters(screen, score_font, texts, balance, kills, pickup_flash, kill_flash)
        draw_hearts(screen, player.hp, player.max_hp)
        draw_weapon_bar(screen, texts, small_font, player)
        if story is not None:
            draw_objective(screen, texts, ui_fonts, story, player.position.x, kills)
        if boss is not None and boss.state == "walk":
            draw_boss_bar(screen, texts, ui_fonts, boss, tr("boss." + boss.kind))
        if toast is not None:
            draw_toast(screen, ui_fonts, toast)
        if banner is not None:
            draw_banner(screen, ui_fonts, banner)
        if state == "play":
            draw_top_buttons(screen, texts, title_font, mouse, not dead)

        screen.blit(texts.get(title_font, tr("hud.line1"), COLOR_TEXT), (20, WINDOW_HEIGHT - 62))
        screen.blit(texts.get(title_font, tr("hud.line2"), COLOR_TEXT), (20, WINDOW_HEIGHT - 40))

        if dead:
            screen.blit(dim_overlay, (0, 0))
            title = texts.get(big_font, tr("dead.title"), COLOR_BAD)
            screen.blit(title, (WINDOW_WIDTH // 2 - title.get_width() // 2, 230))
            sub = texts.get(score_font, tr("dead.stats", k=kills, o=len(collected)), COLOR_TEXT)
            screen.blit(sub, (WINDOW_WIDTH // 2 - sub.get_width() // 2, 325))
            again = tr("dead.retry") if story_on else tr("dead.restart")
            hint = texts.get(score_font, again, COLOR_VELOCITY)
            screen.blit(hint, (WINDOW_WIDTH // 2 - hint.get_width() // 2, 370))

        if state == "pause":
            draw_pause_menu(screen, texts, ui_fonts, mouse, dim_overlay,
                            pause_labels(story_on, fullscreen),
                            disabled=("shop",) if dead else ())
        elif state == "shop":
            draw_shop(screen, texts, ui_fonts, mouse, dim_overlay, player, balance,
                      shop_msg if shop_msg_t > 0.0 else "", shop_msg_ok)
        elif state == "talk":
            draw_dialogue(screen, ui_fonts, dialogue)
        elif state == "win":
            draw_win(screen, texts, ui_fonts, mouse, dim_overlay, kills, len(collected), play_time)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
