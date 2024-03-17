// Copyright (c) 2018 Maen Artimy
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.


// Main code to handle group tables
$(function () {
    var tabsObj = new Tabs('multicast');


    // Get flows data from swicthes
    function loadGroups() {
        expand_form();

        getMulticastGroupData(
            function (src_list) {
                tabsObj.buildTabs("#main2", src_list, "No Multicast groups to show!")
            },
            function (src_list, groups) {
                $.get("/availablenodes")
                    .done(function (data) {
                        let available_dst = data["available_dst"]
                        available_dst.sort(function (a, b) {
                            return a - b;
                        });
                        for (let i in src_list) {
                            let $html_code = $('<form>\n' +
                                '            <fieldset style="margin-bottom: 10px; margin-top: 10px">\n' +
                                '                <legend>Update destination nodes</legend>\n' +
                                '                <div id="checkbox-container-' + src_list[i] + '"></div>\n' +
                                '            </fieldset>\n' +
                                '\n' +
                                '            <div class="formcontrol" style="margin-bottom: 10px; margin-top: 10px">\n' +
                                '                <input type="submit" value="Submit">\n' +
                                '                <input type="reset" value="Clear">\n' +
                                '            </div>\n' +
                                '        </form>')
                            tabsObj.buildContent(src_list[i], $html_code)
                            expand_checkbox_container("checkbox-container-" + src_list[i], available_dst, groups[src_list[i]])
                        }
                        tabsObj.setActive()
                    })
                    .fail(function () {
                        console.log("No Response from server!");
                    });

            });
    }

    function getMulticastGroupData(f, g) {
        $.get("/currentgroups")
            .done(function (groups) {
                // groups: {src: [recv]}

                let src_list = []
                for (let src in groups) {
                    if (groups.hasOwnProperty(src)) {
                        src_list.push(src)
                    }
                }
                f(src_list);
                $.when.apply(this, src_list).then(function () {
                    g(src_list, groups);
                });
            })
            .fail(function () {
                console.log("No Response from server!");
            });
    }

    function expand_form() {
        $.get("/availablenodes")
            .done(function (data) {
                let available_src = data["available_src"]
                let available_dst = data["available_dst"]
                available_src.sort(function (a, b) {
                    return a - b;
                });
                available_dst.sort(function (a, b) {
                    return a - b;
                });
                expand_radio_container("radio-container", available_src)
                expand_checkbox_container("checkbox-container", available_dst, [])
            })
            .fail(function () {
                console.log("No Response from server!");
            });
    }

    function expand_radio_container(id, available_src) {
        // 选择包含单选框的容器元素
        var container = d3.select("#" + id);

        // 为每个数据项创建单选框和标签
        container.selectAll("div")
            .data(available_src)
            .enter()
            .append("div")
            .attr("class", "checkbox-item")
            .html(function (d) {
                return '<input type="radio" id="' + d + '" name="radio_group" value="' + d + '"><label for="' + d + '">' + d + '</label>';
            });
    }

    function expand_checkbox_container(id, available_dst, chosen) {
        // 选择包含复选框的容器元素
        var container = d3.select("#" + id);

        // 为每个数据项创建复选框和标签
        container.selectAll("div")
            .data(available_dst)
            .enter()
            .append("div")
            .attr("class", "checkbox-item")
            .html(function (d) {
                // 检查当前值是否需要被选中
                var isChecked = chosen.includes(d);
                // 如果需要被选中，则设置 checked 属性
                var checkedAttr = isChecked ? 'checked="checked"' : '';
                return '<input type="checkbox" id="' + d + '" name="checkbox_group[]" value="' + d + '" ' + checkedAttr + '><label for="' + d + '">' + d + '</label>';
            });
    }


    // When the refresh button is clicked, clear the page and start over
    $("[name='refresh']").on('click', function () {
        loadGroups();
    })

    loadGroups();

})
