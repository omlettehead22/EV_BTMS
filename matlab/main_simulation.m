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

% Thesis figures (300 dpi PNGs in thesis_results/figures).
% This used to call plot_additional_results.m, which was never committed;
% generate_thesis_figures.m is the plotting routine that took its place.
generate_thesis_figures(resAll,summary,P);

end