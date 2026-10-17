import math

from game_config.const import *
from helper_func import clamp, get_shadow_sprite, lerp
from weapons.guns import draw_weapon
from weapons.knife import draw_knife


# =============================================================================
# 5. THE CHARACTER (articulated stickman)
# =============================================================================

class Stickman:
    """
    A rigid body of mass m moving in a 2D plane, with an angular model
    used only to animate the limbs.
    """

    def __init__(self, x_m, y_m):
        # Inertia and geometry
        self.mass = 70.0  # kg
        self.height_m = 1.3  # total height [m]

        # Dynamic state (SI)
        self.position = pygame.Vector2(x_m, y_m)  # centre of mass G [m]
        self.velocity = pygame.Vector2(0.0, 0.0)  # [m/s]
        self.acceleration = pygame.Vector2(0.0, 0.0)  # [m/s^2]
        self.net_force = pygame.Vector2(0.0, 0.0)  # sum of forces [N]

        # Forces and friction
        self.drive_force = 1000.0  # horizontal muscle force on the ground [N]
        self.air_control = 0.35  # fraction of drive force usable in the air
        self.air_drag = 4.0  # viscous air drag [N.s/m]
        self.ground_friction = 190.0  # viscous ground friction [N.s/m]
        self.max_speed_x = 6.0  # horizontal speed cap [m/s]

        # Jump: pick the target height, derive the launch speed
        # (energy conservation: v0 = sqrt(2 * g * h))
        self.jump_height = 1.15  # m
        self.jump_speed = math.sqrt(2.0 * GRAVITY * self.jump_height)

        self.on_ground = False

        # Combat
        self.hp = PLAYER_MAX_HP
        self.max_hp = PLAYER_MAX_HP
        self.weapon = "knife"  # currently equipped weapon (key of WEAPONS)
        self.weapons_owned = {"knife"}
        self.upgrades = {}  # upgrade key -> level
        self.spent = 0  # orbs spent in the shop
        self.bonus = 0  # orbs given by the story
        self.cooldown_mult = 1.0  # < 1 with "Quick hands"
        self.aim_angle = 0.0  # where the last shot was aimed [rad]
        self.aim_hold = 0.0  # the arm stays raised this long after shooting a gun [s]
        self._release_level = 0.0  # throw_timer value at which the projectile leaves the hand
        self.invuln = 0.0  # invulnerability after a bite [s]
        self.throw_timer = 0.0  # > 0 while the throwing animation plays [s]
        self.throw_cooldown = 0.0  # time until the next throw is allowed [s]
        self._pending_throw = None  # aim angle of a knife that has not left the hand yet

        # Jump handling
        self.jump_buffer = 0.0  # time left on a buffered jump press [s]
        self.jumping = False  # rising after a jump (key may cut it short)
        self.jump_age = 0.0  # time since take-off [s]

        # Animation state
        self.walk_phase = 0.0  # stride cycle angle [rad]
        self.facing = 1  # +1 = right, -1 = left
        self.crouch = 0.0  # 0..1, knees absorbing a landing
        self.air_blend = 1.0  # 0 = ground pose, 1 = mid-air pose

        # Feedback for the main loop (dust, HUD)
        self.events = []  # [("land" | "jump" | "step" | "skid", value)]
        self.last_impact = 0.0  # vertical speed at the last hard landing [m/s]
        self._step_index = 0
        self._skid_timer = 0.0

        self.apply_upgrades()

    def apply_upgrades(self):
        """Recompute every stat that depends on the bought upgrades."""
        self.cooldown_mult = 0.85 ** self.upgrades.get("rate", 0)
        boots = self.upgrades.get("boots", 0)
        # Top speed = drive_force / (ground friction + air drag), so the force has to grow too
        self.drive_force = 1000.0 + 190.0 * 0.8 * boots
        self.max_speed_x = 6.0 + 0.8 * boots
        self.max_hp = PLAYER_MAX_HP + self.upgrades.get("heart", 0)

    def weapon_damage(self):
        return WEAPONS[self.weapon]["damage"] + self.upgrades.get("damage", 0)

    def equip(self, key):
        """Switch weapon (only to one you own). Cancels a throw that has not left the hand yet."""
        if key not in self.weapons_owned:
            return False
        self.weapon = key
        self._pending_throw = None
        self.throw_timer = 0.0
        self.aim_hold = 0.0
        return True

    def press_jump(self):
        """Remember a jump request; it fires as soon as the feet are on the ground."""
        self.jump_buffer = JUMP_BUFFER_S

    def request_throw(self, angle=None):
        """Start a knife throw. The knife leaves the hand halfway through the animation
        (a "throw" event with the aim angle). angle=None means "straight ahead"."""
        if self.throw_cooldown > 0.0 or self.hp <= 0:
            return False
        if angle is None:
            angle = 0.0 if self.facing > 0 else math.pi
        else:
            self.facing = 1 if math.cos(angle) >= 0.0 else -1
        cfg = WEAPONS[self.weapon]
        self._pending_throw = angle
        self.throw_timer = cfg["anim"]
        self._release_level = cfg["anim"] * (1.0 - cfg["release_at"])
        self.throw_cooldown = cfg["cooldown"] * self.cooldown_mult
        if self.weapon != "knife":
            self.aim_angle = angle
            self.aim_hold = 0.35
        return True

    def hand_position(self):
        """World position [m] where a thrown knife leaves the hand."""
        return pygame.Vector2(self.position.x + self.facing * 0.36, self.position.y - 0.36)

    def respawn(self, x_m):
        """Back to a checkpoint: full health, dropped in above `x_m`. Weapons and upgrades are kept."""
        self.position = pygame.Vector2(x_m, 4.0)
        self.velocity = pygame.Vector2(0.0, 0.0)
        self.hp = self.max_hp
        self.invuln = 0.0
        self.on_ground = False
        self.jumping = False
        self.jump_buffer = 0.0
        self._pending_throw = None
        self.throw_timer = 0.0
        self.throw_cooldown = 0.0
        self.aim_hold = 0.0

    def hurt(self, from_dir, damage=1):
        """A zombie bit us (it is on side `from_dir`, +1 right / -1 left): lose hearts and get knocked back."""
        if self.invuln > 0.0 or self.hp <= 0:
            return False
        self.hp -= damage
        self.invuln = INVULNERABLE_S
        self.velocity.x = -from_dir * 5.0
        self.velocity.y = -3.0
        self.on_ground = False
        self.jumping = False
        self.jump_buffer = 0.0
        self._pending_throw = None
        self.throw_timer = 0.0
        self.aim_hold = 0.0
        return True

    def update(self, dt_seconds, move_input, ground_level_m, jump_held=False):
        """Newton's second law + explicit Euler integration."""
        dt = min(dt_seconds, 0.05)  # avoid huge steps after a lag spike
        self.events = []

        # Combat timers; the knife is released in the middle of the throwing animation
        self.invuln = max(0.0, self.invuln - dt)
        self.throw_cooldown = max(0.0, self.throw_cooldown - dt)
        self.aim_hold = max(0.0, self.aim_hold - dt)
        if self.throw_timer > 0.0:
            self.throw_timer = max(0.0, self.throw_timer - dt)
            if self._pending_throw is not None and self.throw_timer <= self._release_level:
                self.events.append(("throw", self._pending_throw))
                self._pending_throw = None

        # Facing direction (locked while a knife is still in the hand)
        if self._pending_throw is None:
            if move_input > 0.05:
                self.facing = 1
            elif move_input < -0.05:
                self.facing = -1

        # Jump: instant vertical impulse, only when standing on the ground
        self.jump_buffer = max(0.0, self.jump_buffer - dt)
        if self.jump_buffer > 0.0 and self.on_ground:
            self.velocity.y = -self.jump_speed
            self.on_ground = False
            self.jumping = True
            self.jump_age = 0.0
            self.jump_buffer = 0.0
            self.events.append(("jump", 0.0))

        # Variable jump height: letting go early cuts the climb short
        if self.jumping:
            self.jump_age += dt
            if self.velocity.y >= 0.0:
                self.jumping = False
            elif not jump_held and self.jump_age > 0.05:
                self.velocity.y *= JUMP_CUT
                self.jumping = False

        # 1. Sum of external forces
        total = pygame.Vector2(0.0, 0.0)

        # Weight: P = m * g
        total += pygame.Vector2(0.0, self.mass * GRAVITY)

        # Muscle drive (weaker in the air)
        control = 1.0 if self.on_ground else self.air_control
        total += pygame.Vector2(move_input * self.drive_force * control, 0.0)

        # Air drag: F = -k * v
        total += -self.air_drag * self.velocity

        if self.on_ground:
            # Normal reaction cancels the weight
            total += pygame.Vector2(0.0, -self.mass * GRAVITY)
            # Ground friction opposes horizontal motion
            total += pygame.Vector2(-self.ground_friction * self.velocity.x, 0.0)

        self.net_force = total

        # 2. a = sum(F) / m
        self.acceleration = self.net_force / self.mass

        # 3. Explicit Euler: v += a*dt, then x += v*dt
        self.velocity += self.acceleration * dt
        self.velocity.x = max(-self.max_speed_x, min(self.max_speed_x, self.velocity.x))

        # Come to a full stop instead of sliding forever at tiny speeds
        if self.on_ground and abs(move_input) < 0.01 and abs(self.velocity.x) < 0.05:
            self.velocity.x = 0.0

        self.position += self.velocity * dt

        # 4. Ground contact (one-sided constraint)
        was_on_ground = self.on_ground
        feet_y = self.position.y + self.height_m / 2.0
        if feet_y >= ground_level_m - 1e-6:
            impact = max(self.velocity.y, 0.0)
            self.position.y = ground_level_m - self.height_m / 2.0
            if self.velocity.y > 0.0:
                self.velocity.y = 0.0
            self.on_ground = True
            if not was_on_ground and impact > 1.0:
                # The harder the landing, the deeper the knees bend
                self.crouch = max(self.crouch, min(impact / 8.0, 1.0))
                self.last_impact = impact
                self.events.append(("land", impact))
        else:
            self.on_ground = False

        # 5. Stride animation, locked to the distance actually travelled
        #    so that the feet do not "skate" over the ground
        if self.on_ground:
            self.walk_phase += self.velocity.x * (2.0 * math.pi / STRIDE_LENGTH_M) * dt
            step_index = math.floor((self.walk_phase - math.pi / 2.0) / math.pi)
            if step_index != self._step_index:
                self._step_index = step_index
                if abs(self.velocity.x) > 2.0:
                    self.events.append(("step", self.velocity.x))

        # Braking hard against the direction of travel: skid and kick up dust
        if self.on_ground and move_input * self.velocity.x < -0.01 and abs(self.velocity.x) > 2.5:
            self._skid_timer -= dt
            if self._skid_timer <= 0.0:
                self._skid_timer = 0.05
                self.events.append(("skid", self.velocity.x))

        # Smooth pose transitions
        self.crouch *= math.exp(-6.0 * dt)
        if self.crouch < 0.01:
            self.crouch = 0.0
        target_air = 0.0 if self.on_ground else 1.0
        self.air_blend += (target_air - self.air_blend) * (1.0 - math.exp(-20.0 * dt))

    def draw_shadow(self, surface, camera_x, ground_level_m):
        """Soft shadow on the ground: shrinks and fades as the runner rises."""
        height = max(0.0, ground_level_m - (self.position.y + self.height_m / 2.0))
        k = min(height / 2.0, 1.0)
        kq = round(k * 10.0) / 10.0  # quantised, so only ~11 sprites ever exist
        width = int(54 * (1.0 - 0.45 * kq))
        thick = max(2, int(11 * (1.0 - 0.45 * kq)))
        shadow = get_shadow_sprite(width, thick, int(120 * (1.0 - 0.7 * kq)))
        # Moonlight comes from the upper right, so the shadow leans to the left
        gx = self.position.x * PIXELS_PER_METER - camera_x - 6 - 14 * k
        surface.blit(shadow,
                     (int(gx - width / 2), int(ground_level_m * PIXELS_PER_METER - thick / 2 + 2)))

    def draw(self, surface, camera_x, ground_level_m, debug=False):
        """Draw the stickman relative to the camera."""
        gx = int(self.position.x * PIXELS_PER_METER - camera_x)
        gy = int(self.position.y * PIXELS_PER_METER)
        ground_px = ground_level_m * PIXELS_PER_METER

        # Body proportions (px)
        head_radius = 12
        torso_len = 36
        thigh_len = 24
        shin_len = 22
        arm_len = 20
        forearm_len = 18

        f = self.facing
        air = self.air_blend
        crouch = self.crouch
        speed = abs(self.velocity.x)
        moving = min(speed / 1.2, 1.0)  # 0 = standing, 1 = on the move
        run = min(speed / self.max_speed_x, 1.0)  # 0..1 of top speed
        lift = max(0.0, -self.velocity.y / self.jump_speed)  # rising amount
        phase = self.walk_phase

        def limb(origin, angle, length):
            """Point at `length` px from `origin`, `angle` rad from straight down."""
            return origin + pygame.Vector2(math.sin(angle) * length, math.cos(angle) * length)

        def mix(ground_value, air_value):
            return ground_value + (air_value - ground_value) * air

        # --- Pose: running / standing / crouching on the ground ---------------
        amp = min(0.30 + 0.04 * speed, 0.55) * moving  # leg swing amplitude [rad]
        swing = math.sin(phase) * amp
        knee_drive = (0.45 + 0.9 * run) * moving  # how high the knee lifts
        ground = {
            "thigh_a": swing + f * 0.95 * crouch,
            "thigh_b": -swing + f * 0.95 * crouch,
            "flex_a": 0.10 * moving + max(0.0, math.cos(phase)) * knee_drive + 1.9 * crouch,
            "flex_b": 0.10 * moving + max(0.0, -math.cos(phase)) * knee_drive + 1.9 * crouch,
            "arm_a": -swing * 1.6 + f * 0.6 * crouch,
            "arm_b": swing * 1.6 + f * 0.6 * crouch,
            "bend": f * (0.35 + 0.9 * run),
        }
        # --- Pose: mid-air (tucks the knees while rising) ---------------------
        in_air = {
            "thigh_a": f * (0.55 + 0.20 * lift),
            "thigh_b": -f * 0.30,
            "flex_a": 0.35 + 1.00 * lift,
            "flex_b": 0.50 + 0.50 * lift,
            "arm_a": f * (-0.70 - 0.60 * lift),
            "arm_b": f * (0.60 + 0.90 * lift),
            "bend": f * 0.5,
        }
        pose = {key: mix(ground[key], in_air[key]) for key in ground}

        if self.weapon == "knife":
            if self.throw_timer > 0.0:
                # Throwing arm: from behind the head, whipping forward to the release point
                u = 1.0 - self.throw_timer / THROW_TIME_S
                e = u * u * (3.0 - 2.0 * u)
                pose["arm_a"] = f * lerp(-2.4, 1.9, e)
                pose["bend"] = f * lerp(0.9, 0.1, e)
        elif self.aim_hold > 0.0:
            # Aiming a gun: the whole arm points at the target (angle measured from straight down)
            pose["arm_a"] = math.pi / 2.0 - self.aim_angle
            pose["bend"] = 0.0

        def leg(thigh_angle, flex):
            """Knee and foot offsets from the pelvis (the knee folds backwards)."""
            knee = limb(pygame.Vector2(0, 0), thigh_angle, thigh_len)
            return knee, limb(knee, thigh_angle - f * flex, shin_len)

        knee_a, foot_a = leg(pose["thigh_a"], pose["flex_a"])
        knee_b, foot_b = leg(pose["thigh_b"], pose["flex_b"])

        # On the ground the lowest foot always touches the floor, so the hips
        # bob naturally while running and sink when the knees bend.
        snap_y = ground_px - max(foot_a.y, foot_b.y)
        pelvis_y = snap_y + (gy + 6 - snap_y) * air
        pelvis = pygame.Vector2(gx, pelvis_y)

        # Torso leans forward with speed (and folds a little when landing)
        lean = clamp(self.velocity.x * 0.06, -0.40, 0.40) + f * 0.40 * crouch * (1.0 - air)
        neck = pelvis + pygame.Vector2(math.sin(lean) * torso_len, -math.cos(lean) * torso_len)
        head = neck + pygame.Vector2(math.sin(lean) * (head_radius + 4),
                                     -math.cos(lean) * (head_radius + 4))

        def seg(color, a, b, width):
            """Line with rounded joints."""
            pygame.draw.line(surface, color, a, b, width)
            pygame.draw.circle(surface, color, (int(b.x), int(b.y)), width // 2)

        def draw_leg(color, knee_off, foot_off, width=4):
            knee, foot = pelvis + knee_off, pelvis + foot_off
            seg(color, pelvis, knee, width)
            seg(color, knee, foot, width)
            pygame.draw.line(surface, color, foot, foot + pygame.Vector2(f * 7, 0), 3)  # flat foot

        def draw_arm(color, angle, width):
            elbow = limb(neck, angle, arm_len)
            hand = limb(elbow, angle + pose["bend"], forearm_len)
            seg(color, neck, elbow, width)
            seg(color, elbow, hand, width)
            return hand

        # Back limbs (grey)
        draw_leg(COLOR_STICKMAN_BACK, knee_b, foot_b)
        draw_arm(COLOR_STICKMAN_BACK, pose["arm_b"], 3)

        # Torso and head
        pygame.draw.line(surface, COLOR_STICKMAN, pelvis, neck, 5)
        pygame.draw.circle(surface, COLOR_STICKMAN, (int(head.x), int(head.y)), head_radius,
                           width=3)
        # Eye shows facing direction
        pygame.draw.circle(surface, COLOR_MARKER, (int(head.x + f * 5), int(head.y - 2)), 2)

        # Front limbs (white)
        draw_leg(COLOR_STICKMAN, knee_a, foot_a)
        hand_a = draw_arm(COLOR_STICKMAN, pose["arm_a"], 4)
        if self.weapon == "knife":
            if self._pending_throw is not None:
                # The knife is still in the hand during the wind-up
                draw_knife(surface, hand_a.x, hand_a.y, math.atan2(-0.9, f * 0.5))
        else:
            hold = self.aim_angle if self.aim_hold > 0.0 else (0.15 if f > 0 else math.pi - 0.15)
            draw_weapon(surface, self.weapon, hand_a.x, hand_a.y, hold)

        if debug:
            # Centre of mass G and velocity vector
            pygame.draw.circle(surface, COLOR_CENTER, (gx, gy), 4)
            tip_x = gx + int(self.velocity.x * PIXELS_PER_METER * 0.25)
            tip_y = gy + int(self.velocity.y * PIXELS_PER_METER * 0.25)
            pygame.draw.line(surface, COLOR_VELOCITY, (gx, gy), (tip_x, tip_y), 3)
