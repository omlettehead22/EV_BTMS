function validation_no_pcm()
%VALIDATION_NO_PCM  Run a case with PCM effectively disabled.

P = params_materials();
% Disable PCM latent heat and make cp constant
P.L_pcm       = 0;
P.Tm_solid    = 0;
P.Tm_liquid   = 0;
P.cp_pcm_solid= P.cp_cell;
P.cp_pcm_liquid= P.cp_cell;

scenarioType = 'charge';
bcType       = 'air';
hLevel       = 'high';
T_env        = P.T_amb_mild;

res = run_scenario_1D(P, scenarioType, bcType, hLevel, T_env);

figure; plot(res.t, res.Tmax - 273.15);
xlabel('Time [s]');
ylabel('Max cell temperature [°C]');
grid on;
title('Validation run: no PCM, charge-air-high');

fprintf('Peak Tmax (no PCM) = %.2f °C\n', max(res.Tmax - 273.15));
end