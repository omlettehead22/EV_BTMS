function sensitivity_pcm_properties()
%SENSITIVITY_PCM_PROPERTIES  Sensitivity of Tmax to PCM latent heat and melting window.
%
% Uses params_materials.m as a baseline (RT31-type PCM) and sweeps around:
% - latent heat L_pcm
% - melting interval (Tm_solid, Tm_liquid)
% under a fixed scenario and event duration.

%% 1. Baseline parameters and scenario
P_base = params_materials();

scenarioType = 'charge';
bcType       = 'liquid';
hLevel       = 'mid';

T_env = P_base.T_coolant;      % K
t_end = P_base.t_end_charge;   % 3600 s by default

%% 2. PCM parameter grids
% Latent heat values [J/kg] around baseline
L_pcm_values = [120e3, 160e3, 220e3];

% Melting window shifts [°C] relative to baseline 29–34 °C
% negative shift: lower melting range; positive shift: higher range
Tm_shift_C   = [-2, 0, +2];

nL  = numel(L_pcm_values);
nTm = numel(Tm_shift_C);

% Storage for peak temperatures
T_peak_matrix = zeros(nL, nTm);

%% 3. Double loop over PCM latent heat and melting window
for iL = 1:nL
    for jTm = 1:nTm
        % Copy baseline and modify PCM properties
        P = P_base;
        P.L_pcm = L_pcm_values(iL);

        shift = Tm_shift_C(jTm);
        P.Tm_solid = (29 + shift) + 273.15;
        P.Tm_liquid = (34 + shift) + 273.15;

        % Run scenario
        res = run_scenario_1D(P, scenarioType, bcType, hLevel, T_env, t_end);
        T_C = res.Tmax - 273.15;
        T_peak_matrix(iL, jTm) = max(T_C);
    end
end

%% 4. Plot results: peak temperature vs melting shift for each latent heat
figure; hold on;
colors = lines(nL);
for iL = 1:nL
    plot(Tm_shift_C, T_peak_matrix(iL,:), 'o-', ...
        'Color', colors(iL,:), ...
        'DisplayName', sprintf('L_{pcm} = %.0f kJ/kg', L_pcm_values(iL)/1e3));
end
xlabel('Melting window shift [°C] (from baseline 29–34 °C)');
ylabel('Peak T_{max} [°C]');
title(sprintf('Sensitivity of peak temperature to PCM properties (%s-%s-%s, t_{end} = %ds)', ...
    scenarioType, bcType, hLevel, t_end));
legend('Location','best');
grid on;

%% 5. Print matrix for clarity
fprintf('\nPeak Tmax [°C] for %s-%s-%s, T_env = %.1f °C, t_end = %ds:\n', ...
    scenarioType, bcType, hLevel, T_env - 273.15, t_end);
fprintf('Rows: L_pcm = [%.0f %.0f %.0f] kJ/kg; Cols: Tm_shift = [-2 0 +2] °C\n', ...
    L_pcm_values(1)/1e3, L_pcm_values(2)/1e3, L_pcm_values(3)/1e3);
disp(T_peak_matrix);
end