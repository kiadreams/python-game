import pygame


# =============================================================================
# 2. SMALL HELPERS
# =============================================================================

def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def hash01(n, salt=0):
    """Deterministic pseudo-random number in [0, 1) from an integer.
    Lets the scenery be 'infinite' yet identical every time you come back."""
    n = (n * 374761393 + salt * 668265263 + 144665) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 4294967296.0


def make_glow(radius, color, strength=1.0):
    """Opaque radial gradient on black, meant to be blitted with BLEND_RGB_ADD."""
    surf = pygame.Surface((radius * 2, radius * 2))
    surf.fill((0, 0, 0))
    for r in range(radius, 0, -1):
        k = (1.0 - r / radius) ** 2 * strength
        pygame.draw.circle(
            surf, (int(color[0] * k), int(color[1] * k), int(color[2] * k)), (radius, radius), r
        )
    return surf.convert()


_SHADOW_SPRITES = {}


def get_shadow_sprite(width, thick, alpha):
    """Soft ellipse shadow. Sprites are cached instead of being re-created every frame."""
    key = (width, thick, alpha)
    sprite = _SHADOW_SPRITES.get(key)
    if sprite is None:
        sprite = pygame.Surface((width, thick), pygame.SRCALPHA)
        pygame.draw.ellipse(sprite, (0, 0, 0, alpha), sprite.get_rect())
        sprite = _SHADOW_SPRITES[key] = sprite.convert_alpha()
    return sprite
