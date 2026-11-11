function [summary,resAll] = main_simulation()
%MAIN_SIMULATION Run baseline scenarios and export results.

P = params_materials();
scenarios = define_scenarios(P);

resAll = run_all_scenarios(P,scenarios);

% Plot maximum-temperature curves
plot_Tmax_curves(resAll);

% Produce summary table
summary = summarise_scenario_metrics(resAll);

fprintf('\nScenario summary:\n');
disp(summary);

% Create output directory
outputFolder = 'thesis_results';

if ~exist(outputFolder,'dir')
    mkdir(outputFolder);
end

% Export numerical summary
writetable(summary,...
    fullfile(outputFolder,'BTMS_results_summary.csv'));

% Save complete simulation results
save(fullfile(outputFolder,'BTMS_complete_results.mat'),...
    'P','scenarios','resAll','summary');

fprintf('\nResults exported to %s\n',outputFolder);

% Run the original additional plotting function if available
if exist('plot_additional_results','file') == 2
    plot_additional_results(resAll,scenarios,summary);
else
    warning(['plot_additional_results.m was not found. ',...
        'The numerical results were still exported successfully.']);
end

end