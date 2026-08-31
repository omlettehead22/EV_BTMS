function run_time_step_verification()
%RUN_TIME_STEP_VERIFICATION
% Check numerical sensitivity to the implicit time step.

% Final time steps to test
dtValues = [1.0, 0.5, 0.25, 0.125];

% Use the charge-liquid-mid case as the verification scenario
scenarioType = 'charge';
bcType       = 'liquid';
hLevel       = 'mid';

% Load base parameters
Pbase = params_materials();

% Prescribe environment temperature in the same way as define_scenarios
if isfield(Pbase,'Tcoolant')
    Tenv = Pbase.Tcoolant;
elseif isfield(Pbase,'T_coolant')
    Tenv = Pbase.T_coolant;
else
    error('No coolant-temperature field found. Available fields are:\n%s', ...
        strjoin(fieldnames(Pbase),newline));
end
% Store results
peakT_C    = zeros(numel(dtValues),1);
finalT_C   = zeros(numel(dtValues),1);
balancePct = zeros(numel(dtValues),1);
runTime_s  = zeros(numel(dtValues),1);

for i = 1:numel(dtValues)

    % Copy the parameter structure
    P = Pbase;

    % Override time step
    P.dt = dtValues(i);

    % Time the individual simulation
    tic;
    res = run_scenario_1D( ...
        P, ...
        scenarioType, ...
        bcType, ...
        hLevel, ...
        Tenv);
    runTime_s(i) = toc;

    % Convert K to degC
    T_C = res.t(:).*0 + res.Tmax(:) - 273.15;

    peakT_C(i)  = max(T_C);
    finalT_C(i) = T_C(end);

    if isfield(res,'balance_error_pct')
        balancePct(i) = res.balance_error_pct;
    else
        balancePct(i) = NaN;
    end
end

% Build output table
timeStepTable = table( ...
    dtValues(:), ...
    peakT_C, ...
    finalT_C, ...
    balancePct, ...
    runTime_s, ...
    'VariableNames',{ ...
        'TimeStep_s', ...
        'PeakTemperature_C', ...
        'FinalTemperature_C', ...
        'BalanceError_pct', ...
        'Runtime_s'});

disp(timeStepTable);

% Create output folder
outputFolder = fullfile('thesis_results','figures');
if ~exist(outputFolder,'dir')
    mkdir(outputFolder);
end

% Save numerical values
writetable(timeStepTable, ...
    fullfile('thesis_results','time_step_verification.csv'));

% Plot results
f = figure('Color','w','Position',[100 100 900 500]);

yyaxis left
plot(dtValues,peakT_C,'o-', ...
    'LineWidth',2, ...
    'MarkerSize',7, ...
    'MarkerFaceColor',[0.10 0.42 0.68]);
ylabel('Peak cell temperature, ^\circC');

yyaxis right
plot(dtValues,balancePct,'s--', ...
    'LineWidth',2, ...
    'MarkerSize',7, ...
    'MarkerFaceColor',[0.85 0.33 0.10]);
ylabel('Energy-balance error, %');

xlabel('Time step, s');
title('Temporal convergence of the charge-liquid-mid case');
grid on;
box on;

legend({'Peak temperature','Balance error'}, ...
    'Location','best');

% Export thesis-ready PNG
exportgraphics(f, ...
    fullfile(outputFolder,'figure_3_5_timestep_convergence.png'), ...
    'Resolution',300);

fprintf('\nTime-step verification complete.\n');
fprintf('Results saved to thesis_results/time_step_verification.csv\n');
fprintf('Figure saved to thesis_results/figures/figure_3_5_timestep_convergence.png\n');

end