import numpy as np
from dataclasses import dataclass
from wind_generator import IWindField


@dataclass
class BoatState:
    """State of the boat."""
    x: float
    y: float
    psi: float
    Vx: float  # Body-frame x velocity
    Vy: float  # Body-frame y velocity
    omega: float
    adapt_param1: float # estimation of the forward force uncertanty
    adapt_param2: float # estimation of the Moment force uncertanty

    @classmethod
    def from_array(cls, arr: np.ndarray) -> 'BoatState':
        """Creates a BoatState object from a numpy array."""
        if len(arr) != 8:
            raise ValueError("Array must have exactly 8 elements.")
        return cls(arr[0], arr[1], arr[2], arr[3], arr[4], arr[5], arr[6], arr[7])

    def to_array(self) -> np.ndarray:
        """Converts the boat state to a numpy array."""
        return np.array([self.x, self.y, self.psi, self.Vx, self.Vy, self.omega, self.adapt_param1, self.adapt_param2])

    def _wrap_angle(self, angle):
        """Wraps angle to [-pi, +pi] using atan2-style wrapping."""
        return (angle + np.pi) % (2 * np.pi) - np.pi

    def update(self, derivatives: np.ndarray, dt: float) -> None:
        """Updates the boat state using Euler integration."""
        if len(derivatives) != 8:
            raise ValueError("Derivatives must have exactly 8 elements.")
        self.x += derivatives[0] * dt
        self.y += derivatives[1] * dt
        self.psi += derivatives[2] * dt
        self.psi = self._wrap_angle(self.psi)
        self.Vx += derivatives[3] * dt
        self.Vy += derivatives[4] * dt
        self.omega += derivatives[5] * dt
        self.adapt_param1 += derivatives[6] * dt
        self.adapt_param2 += derivatives[7] * dt


@dataclass
class BoatParameters:
    """Parameters of the boat."""
    mass: float
    inertia: float
    damping: list  # [Dx, Dy, Dpsi] damping coefficients
    L: float  # Distance from CoM to thruster
    air_density: float # kg/m³ (standard air)
    sail_Cx: float # Surge drag coefficient  
    sail_Cy: float # Sway drag coefficient
    sail_area: float # m² (example sail area)


class Boat:
    """Base class for boat dynamics with thrusters."""
    def __init__(self, init_state: BoatState, params: BoatParameters, wind_field: IWindField):
        """
        Initializes the Boat object with initial conditions and system parameters.
        
        Args:
            init_state: Initial state of the boat
            params: Boat parameters
            wind_field: Class to get wind vector field [Vx_wind, Vy_wind]
        """
        self.state: BoatState = init_state
        self.params: BoatParameters = params
        self.wind_field: IWindField = wind_field  # Wind in global frame [Vw_x, Vw_y]

    def dynamics(self, control: np.ndarray) -> np.ndarray:
        """
        Computes the dynamics of the vessel based on the current control inputs.

        Returns:
            np.ndarray: Derivative of the vessel's state [dx, dy, dpsi, dVx, dVy, domega].
        """
        raise NotImplementedError("Dynamics method not implemented.")

    def _kinematics(self, Fx: float, Fy: float, M: float) -> np.ndarray:
        """
        Computes the kinematics of the vessel based on forces and moments,
        including wind sail dynamics.

        Returns:
            np.ndarray: Derivative of the vessel's state [dx, dy, dpsi, dVx, dVy, domega].
        """
        # Kinematics
        dx = self.state.Vx * np.cos(self.state.psi) - self.state.Vy * np.sin(self.state.psi)
        dy = self.state.Vx * np.sin(self.state.psi) + self.state.Vy * np.cos(self.state.psi)
        dpsi = self.state.omega

        # Initialize sail forces
        F_sail_x, F_sail_y = 0.0, 0.0

        # Calculate wind effects if wind field exists
        if self.wind_field is not None:
            # Get global wind velocity
            V_wx_global, V_wy_global = self.wind_field.get_wind([self.state.x, self.state.y])
            
            # Transform to boat's body frame
            V_wx_body = np.cos(self.state.psi) * V_wx_global + np.sin(self.state.psi) * V_wy_global
            V_wy_body = -np.sin(self.state.psi) * V_wx_global + np.cos(self.state.psi) * V_wy_global
            
            # Calculate apparent wind angle and speed difference
            V_aw_x = V_wx_body - self.state.Vx
            V_aw_y = V_wy_body - self.state.Vy
            
            # Calculate sail forces (using boat parameters)
            Wind_Force = 0.5 * self.params.air_density * self.params.sail_area
            F_sail_x = Wind_Force * self.params.sail_Cx * V_aw_x
            F_sail_y = Wind_Force * self.params.sail_Cy * V_aw_y

        # Dynamics with sail forces
        dVx = ((Fx + F_sail_x) / self.params.mass) - self.params.damping[0] * self.state.Vx
        dVy = ((Fy + F_sail_y) / self.params.mass) - self.params.damping[1] * self.state.Vy
        domega = (M / self.params.inertia) - self.params.damping[2] * self.state.omega
        return np.array([dx, dy, dpsi, dVx, dVy, domega])

    def update_state(self, control: np.ndarray, adaptation_derivatives: np.ndarray, dt: float) -> None:
        """Updates state using Euler integration."""
        derivatives = np.concatenate([self.dynamics(control), adaptation_derivatives])
        self.state.update(derivatives, dt)


class DifferentialThrustBoat(Boat):
    """Boat with two fixed thrusters (left/right)."""
    def dynamics(self, control: np.ndarray) -> np.ndarray:
        Fx = control[0] + control[1]  # Sum of thrusts
        Fy = 0  # No lateral force
        M = self.params.L * (control[1] - control[0])  # Differential torque
        return self._kinematics(Fx, Fy, M)


class SteerableThrustBoat(Boat):
    """Boat with a single steerable thruster."""
    def dynamics(self, control: np.ndarray) -> np.ndarray:
        thrust, theta = control[0], control[1]
        Fx = thrust * np.cos(theta)
        Fy = thrust * np.sin(theta)
        M = thrust * self.params.L * np.sin(theta)  # Torque from offset
        return self._kinematics(Fx, Fy, M)