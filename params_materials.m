function P = params_materials()
%PARAMS_MATERIALS  Define geometry, material properties and basic settings.
%
% Values based on:
% - RT31 paraffin PCM datasheet (Rubitherm).
% - Paraffin PCM reviews for thermal management.
% - 6061-T6 aluminum datasheets
% - Meta-analyses of Li-ion cell thermal properties 
% - BTMS convective coefficient ranges and practice.
%% Geometry (radial line: cell centre → PCM → casing)
P.r_cell_inner = 0.0;
P.r_cell_outer = 0.009;     % ~9 mm radius for 18650-type cell.
P.r_pcm_outer  = 0.012;     % PCM thickness ~3 mm.
P.r_case_outer = 0.013;     % casing thickness ~1 mm.
P.L_axial       = 0.065;   % m, axial length of the cell (e.g. 65 mm)
P.Nx = 130;

%% Cell properties (NMC 18650-type)
P.rho_cell = 2500;          % kg/m^3.
P.cp_cell  = 1040;          % J/kgK (typical NMC cell cp).
P.k_cell   = 0.9;           % W/mK (radial direction).

%% PCM properties (RT31-type paraffin)
P.rho_pcm        = 830;            % kg/m^3 (solid).
P.cp_pcm_solid   = 2000;           % J/kgK (below melting).
P.cp_pcm_liquid  = 2300;           % J/kgK (above melting).
P.k_pcm          = 0.2;            % W/mK.
P.Tm_solid       = 29 + 273.15;    % K, start of melting.
P.Tm_liquid      = 34 + 273.15;    % K, end of melting.
P.L_pcm          = 160e3;          % J/kg latent heat.

%% Casing properties (Al 6061-T6)
P.rho_case = 2700;          % kg/m^3.
P.cp_case  = 900;           % J/kgK (~896 rounded).
P.k_case   = 170;           % W/mK (approx 166–180).
%% Air-side convective coefficients (forced air).
P.h_air_low  = 10;          % W/m^2K.
P.h_air_mid  = 30;          % W/m^2K.
P.h_air_high = 60;          % W/m^2K.

%% Liquid-side convective coefficients (cold plate).
P.h_liq_low  = 100;         % W/m^2K.
P.h_liq_mid  = 300;         % W/m^2K.
P.h_liq_high = 600;         % W/m^2K.

%% Ambient and coolant temperatures
P.T_amb_mild = 25 + 273.15;  % K.
P.T_amb_warm = 30 + 273.15;  % K.
P.T_coolant  = 25 + 273.15;  % K.

%% Time-stepping settings
P.dt          = 0.5;        % s.
P.t_end_drive = 600;        % s.
P.t_end_charge= 3600;       % s.

%% Auxiliary power (fan/pump) estimates (pack-level order).
P.P_fan_low   = 10;         % W.
P.P_fan_mid   = 20;         % W.
P.P_fan_high  = 40;         % W.
P.P_pump_low  = 10;         % W.
P.P_pump_mid  = 40;         % W.
P.P_pump_high = 80;         % W.

%% Initial condition
P.T_initial = 25 + 273.15; % K

P.nonlinear_tolerance = 1e-7; % K
P.nonlinear_max_iterations = 30;
P.nonlinear_relaxation = 0.7;
end